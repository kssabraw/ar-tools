"""Cross-module "your content is still generating" awareness.

Long content jobs (ecommerce pages, Local SEO / location / service pages, blog
posts) run server-side as background work, so a user can kick off a batch and
navigate away. This module gives them two things:

1. A **live activity read** (`list_user_activity`) — every in-flight
   content job the user started, across all clients, for a global "N pages
   still generating" indicator that follows them everywhere.
2. A **batch-completion notification** (`on_content_job_settled`, driven from
   the job worker) — when the last job of a user's batch for a client finishes,
   emit one Activity notification ("Your 69 ecommerce pages for Nova Life
   Peptides finished — 66 done, 3 failed") through the shared notifications
   service, so they learn it's done even with the tab closed.

Content pages are `async_jobs` rows carrying `payload.user_id` + `entity_id`
(the client). Blog posts live in the separate `runs` table (`created_by` +
non-terminal statuses) and are read for the live indicator only — their own
Runs page already tracks completion.

Best-effort throughout: a failure here never breaks the worker or an API call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# ── content job taxonomy ─────────────────────────────────────────────────────
# async_jobs job_types that represent a user-visible content page being written
# (or rewritten). Scoring/planning jobs (ecommerce_action, local_seo_silo) are
# NOT content and are deliberately excluded.
_FAMILY_TYPES: dict[str, tuple[str, ...]] = {
    "ecommerce": ("ecommerce_generate", "ecommerce_reoptimize_url"),
    "local_seo": ("local_seo_generate", "local_seo_reoptimize_url"),
}
_FAMILY_LABEL = {"ecommerce": "Ecommerce", "local_seo": "Local SEO"}
# Flat set of every content job_type, and a reverse job_type -> family map.
CONTENT_JOB_TYPES: set[str] = {t for types in _FAMILY_TYPES.values() for t in types}
_TYPE_FAMILY: dict[str, str] = {
    t: fam for fam, types in _FAMILY_TYPES.items() for t in types
}

_IN_FLIGHT = ("pending", "running")
_CANCELLED_ERROR = "cancelled_by_user"
# How far back to look when reconstructing "this batch" at completion time.
_BATCH_WINDOW_HOURS = 12
# A gap between job creation times larger than this starts a new batch (bulk
# enqueues stamp created_at within the same second; a separate run is minutes+
# apart), so back-to-back batches aren't merged into one notification.
_BATCH_GAP_SECONDS = 300


# ── single-job activity registry ─────────────────────────────────────────────
# Non-content, user-initiated long jobs (one job == one user-visible task, no
# per-item batch fan-out). Registering a type does two things: it surfaces the
# in-flight job in the global Activity indicator, and — when `notify` — emits one
# personal "task finished" notification to the initiating user's header bell
# (`recipient_profile_id`) when the job settles.
#
# EVERY entry is gated on the job carrying `payload.user_id`, so the *scheduled /
# background* runs of the same type (daily sweeps, auto-scans at client creation
# — no user_id) never appear here or ping anyone. Only a run a user kicked off
# and might navigate away from surfaces. `path` is a relative in-app link
# ({cid} = the job's client id). `notify=False` shows the job in the indicator
# but leaves completion messaging to a bespoke producer (avoids double-pinging).
SINGLE_JOB_REGISTRY: dict[str, dict[str, Any]] = {
    "keyword_research":        {"label": "Keyword research",        "path": "clients/{cid}/keyword-research", "notify": True},
    "keyword_topic_research":  {"label": "Topic research",          "path": "clients/{cid}/keyword-research", "notify": True},
    "keyword_research_report": {"label": "Keyword research report", "path": "clients/{cid}/keyword-research", "notify": True},
    "domain_overview":         {"label": "Domain overview",         "path": "clients/{cid}/domain-intel",     "notify": True},
    "keyword_gap":             {"label": "Keyword gap",             "path": "clients/{cid}/domain-intel",     "notify": True},
    "link_gap":                {"label": "Backlink gap",            "path": "clients/{cid}/domain-intel",     "notify": True},
    "local_seo_silo":          {"label": "Silo plan",               "path": "clients/{cid}/local-seo",        "notify": True},
    "service_page_plan":       {"label": "Service page plan",       "path": "clients/{cid}/service-pages",    "notify": True},
    "gsc_research":            {"label": "GSC research",            "path": "clients/{cid}/gsc-research",     "notify": True},
    "client_report":          {"label": "Client report",           "path": "clients/{cid}/reports",          "notify": True},
    "brand_report":           {"label": "AI visibility report",    "path": "clients/{cid}/ai-visibility",    "notify": True},
    "brand_scan":             {"label": "AI visibility scan",      "path": "clients/{cid}/ai-visibility",    "notify": True},
    "brand_voice_scan":       {"label": "Brand voice scan",        "path": "clients/{cid}/brand-voice",      "notify": True},
    "icp_scan":               {"label": "ICP scan",                "path": "clients/{cid}/icp",              "notify": True},
    "rank_keyword_report":    {"label": "Rank analysis report",    "path": "clients/{cid}/rankings",         "notify": True},
    "backlink_lookup":        {"label": "Backlink lookup",         "path": "clients/{cid}/backlinks",        "notify": True},
    "article_reanalyze":      {"label": "Article reanalysis",      "path": "clients/{cid}/articles",         "notify": True},
}

# Every job_type the Activity indicator reads: content page jobs (batch-tracked)
# + the single-job registry. Membership is safe regardless of scheduled runs —
# the user_id gate keeps background runs out.
ACTIVITY_JOB_TYPES: frozenset[str] = frozenset(CONTENT_JOB_TYPES) | frozenset(SINGLE_JOB_REGISTRY)


def family_for(job_type: Optional[str]) -> Optional[str]:
    """Return the content family ('ecommerce' | 'local_seo') for a job_type, or
    None if it isn't a content job."""
    return _TYPE_FAMILY.get(job_type or "")


def _client_id_of(job: dict) -> Optional[str]:
    # Prefer payload.client_id: for content jobs it equals entity_id, but some
    # single jobs set entity_id to a non-client id (e.g. rank_keyword_report uses
    # the report id) while carrying the real client in the payload.
    cid = (job.get("payload") or {}).get("client_id") or job.get("entity_id")
    return str(cid) if cid else None


def _user_id_of(job: dict) -> Optional[str]:
    uid = (job.get("payload") or {}).get("user_id")
    return str(uid) if uid else None


# ── live activity read (the global indicator) ────────────────────────────────

def _client_name_map(supabase, client_ids: set[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    try:
        rows = (
            supabase.table("clients")
            .select("id, name")
            .in_("id", list(client_ids))
            .execute()
        ).data or []
        return {str(r["id"]): r.get("name") or "Client" for r in rows}
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("activity.client_names_failed", extra={"error": str(exc)})
        return {}


def _job_item(job: dict, names: dict[str, str]) -> dict[str, Any]:
    job_type = job.get("job_type") or ""
    cid = _client_id_of(job) or ""
    payload = job.get("payload") or {}
    content_fam = _TYPE_FAMILY.get(job_type)
    if content_fam:  # a content page job (batch-tracked family)
        fam = content_fam
        kind_label = _FAMILY_LABEL.get(fam, "Content")
        mode = "reoptimize" if job_type.endswith("reoptimize_url") else "generate"
        href = f"/clients/{cid}/{'ecommerce' if fam == 'ecommerce' else 'local-seo'}" if cid else None
        label = payload.get("keyword") or payload.get("page_url") or "Page"
    else:  # a single registered task job
        desc = SINGLE_JOB_REGISTRY.get(job_type, {})
        fam = "task"
        kind_label = desc.get("label", "Task")
        mode = "generate"
        path = desc.get("path")
        href = f"/{path.format(cid=cid)}" if (path and cid) else None
        label = payload.get("keyword") or payload.get("label") or kind_label
    return {
        "id": str(job.get("id")),
        "source": "job",
        "family": fam,
        "kind_label": kind_label,
        "mode": mode,
        "client_id": cid,
        "client_name": names.get(cid, "Client"),
        "label": label,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "href": href,
    }


def _run_item(run: dict, names: dict[str, str]) -> dict[str, Any]:
    cid = str(run.get("client_id") or "")
    ctype = (run.get("content_type") or "blog_post").replace("_", " ")
    return {
        "id": str(run.get("id")),
        "source": "run",
        "family": "blog",
        "kind_label": ctype.title(),
        "mode": "generate",
        "client_id": cid,
        "client_name": names.get(cid, "Client"),
        "label": run.get("keyword") or "Article",
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "href": f"/runs/{run.get('id')}",
    }


def list_user_activity(user_id: str) -> dict[str, Any]:
    """Every in-flight content job the user started, across all clients.

    Unions async_jobs content jobs (ecommerce / Local SEO pages) with
    non-terminal `runs` (blog posts). Returns a flat, newest-first item list and
    a per-client grouping for the global Activity indicator + panel."""
    from services.orchestrator import NON_TERMINAL_STATUSES

    supabase = get_supabase()
    jobs: list[dict] = []
    runs: list[dict] = []
    try:
        jobs = (
            supabase.table("async_jobs")
            .select("id, job_type, entity_id, payload, status, created_at")
            .in_("job_type", list(ACTIVITY_JOB_TYPES))
            .in_("status", list(_IN_FLIGHT))
            .eq("payload->>user_id", user_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("activity.jobs_query_failed", extra={"error": str(exc)})
    try:
        runs = (
            supabase.table("runs")
            .select("id, keyword, client_id, content_type, status, created_at")
            .eq("created_by", user_id)
            .in_("status", list(NON_TERMINAL_STATUSES))
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("activity.runs_query_failed", extra={"error": str(exc)})

    client_ids = {c for c in (
        [_client_id_of(j) for j in jobs] + [str(r.get("client_id")) for r in runs]
    ) if c}
    names = _client_name_map(supabase, client_ids)

    items = [_job_item(j, names) for j in jobs] + [_run_item(r, names) for r in runs]
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)

    groups: dict[str, dict[str, Any]] = {}
    for it in items:
        g = groups.setdefault(
            it["client_id"],
            {"client_id": it["client_id"], "client_name": it["client_name"], "count": 0, "families": {}},
        )
        g["count"] += 1
        g["families"][it["kind_label"]] = g["families"].get(it["kind_label"], 0) + 1

    return {"count": len(items), "items": items, "groups": list(groups.values())}


# ── batch-completion notification (driven from the job worker) ───────────────

def _latest_batch(rows: list[dict], gap_seconds: int = _BATCH_GAP_SECONDS) -> list[dict]:
    """Isolate the most recent contiguous batch from terminal jobs (newest
    first), splitting on a creation-time gap so an earlier batch in the same
    window isn't merged in. Pure — unit-tested."""
    if not rows:
        return []
    parsed = []
    for r in rows:
        ts = _parse_ts(r.get("created_at"))
        if ts is not None:
            parsed.append((ts, r))
    if not parsed:
        return [rows[0]]
    parsed.sort(key=lambda p: p[0], reverse=True)
    kept = [parsed[0][1]]
    prev = parsed[0][0]
    for ts, r in parsed[1:]:
        if (prev - ts).total_seconds() > gap_seconds:
            break
        kept.append(r)
        prev = ts
    return kept


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def summarize_batch(rows: list[dict]) -> dict[str, int]:
    """Count done / failed / cancelled over a batch's terminal jobs. Pure."""
    done = failed = cancelled = 0
    for r in rows:
        status = r.get("status")
        if status == "complete":
            done += 1
        elif status == "failed":
            if (r.get("error") or "") == _CANCELLED_ERROR:
                cancelled += 1
            else:
                failed += 1
    return {"done": done, "failed": failed, "cancelled": cancelled, "total": done + failed + cancelled}


def build_batch_notification(family: str, client_name: str, counts: dict[str, int]) -> Optional[dict]:
    """Build the {title, summary} for a finished batch, or None if there's
    nothing worth announcing (e.g. the whole batch was cancelled). Pure."""
    done, failed, cancelled = counts["done"], counts["failed"], counts["cancelled"]
    if done == 0 and failed == 0:
        return None  # nothing produced (all cancelled) — user already knows
    label = _FAMILY_LABEL.get(family, "Content")
    unit = "pages" if (done + failed) != 1 else "page"
    title = f"{label} {unit} finished"
    parts = [f"{done} done"]
    if failed:
        parts.append(f"{failed} failed")
    if cancelled:
        parts.append(f"{cancelled} cancelled")
    summary = f"Your {label.lower()} batch for {client_name} finished — {', '.join(parts)}."
    return {"title": title, "summary": summary}


def on_content_job_settled(job: dict) -> None:
    """Called by the job worker after a content job reaches a terminal state.

    If it was the LAST in-flight content job of its (user, client, family)
    group, emit one batch-completion notification. Single-worker execution makes
    "last to finish" race-free; the notification dedupe_key makes any redelivery
    a clean no-op. Best-effort — never raises."""
    try:
        family = family_for(job.get("job_type"))
        if not family:
            return
        user_id = _user_id_of(job)
        client_id = _client_id_of(job)
        if not user_id or not client_id:
            return
        types = list(_FAMILY_TYPES[family])
        supabase = get_supabase()

        remaining = (
            supabase.table("async_jobs")
            .select("id", count="exact")
            .in_("job_type", types)
            .in_("status", list(_IN_FLIGHT))
            .eq("entity_id", client_id)
            .eq("payload->>user_id", user_id)
            .execute()
        ).count or 0
        if remaining > 0:
            return  # batch still running

        window_start = (datetime.now(timezone.utc) - timedelta(hours=_BATCH_WINDOW_HOURS)).isoformat()
        terminal = (
            supabase.table("async_jobs")
            .select("id, status, error, created_at")
            .in_("job_type", types)
            .in_("status", ["complete", "failed"])
            .eq("entity_id", client_id)
            .eq("payload->>user_id", user_id)
            .gte("completed_at", window_start)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
        batch = _latest_batch(terminal)
        if not batch:
            return
        counts = summarize_batch(batch)
        note = build_batch_notification(family, _lookup_client_name(supabase, client_id), counts)
        if not note:
            return

        started = min((_parse_ts(r.get("created_at")) for r in batch if _parse_ts(r.get("created_at"))), default=None)
        stamp = started.strftime("%Y%m%d%H%M") if started else "x"
        notifications.emit(
            client_id=client_id,
            kind="content_batch",
            title=note["title"],
            summary=note["summary"],
            severity="info",
            payload={"family": family, "user_id": user_id, "link": _family_link(family, client_id), **counts},
            dedupe_key=f"content_batch:{user_id}:{client_id}:{family}:{stamp}",
            recipient_profile_id=user_id,
        )
    except Exception as exc:  # pragma: no cover - best effort
        logger.error("activity.settle_failed", extra={"job_id": job.get("id"), "error": str(exc)})


def _family_link(family: str, client_id: str) -> str:
    return f"clients/{client_id}/{'ecommerce' if family == 'ecommerce' else 'local-seo'}"


# ── single-job completion notification (driven from the job worker) ──────────

def single_job_notification(
    job_type: str, client_name: str, status: str, error: Optional[str] = None,
) -> Optional[dict]:
    """Build the {title, summary, severity} for a settled single (non-batch) job,
    or None if it isn't a notifying registered type or the outcome is silent
    (cancelled). Pure — unit-tested."""
    desc = SINGLE_JOB_REGISTRY.get(job_type)
    if not desc or not desc.get("notify"):
        return None
    label = desc["label"]
    if status == "complete":
        return {
            "title": f"{label} finished",
            "summary": f"Your {label.lower()} for {client_name} is ready.",
            "severity": "info",
        }
    if status == "failed":
        if (error or "") == _CANCELLED_ERROR:
            return None  # user cancelled — they already know
        reason = f" — {error}" if error else ""
        return {
            "title": f"{label} failed",
            "summary": f"Your {label.lower()} for {client_name} didn't finish{reason}.",
            "severity": "warning",
        }
    return None


def _on_single_job_settled(job: dict) -> None:
    """Emit one personal completion notification to the user who started a settled
    single job. Idempotent via a job-id dedupe_key (a reaper re-run is a clean
    no-op). Best-effort — never raises."""
    job_type = job.get("job_type") or ""
    user_id = _user_id_of(job)
    client_id = _client_id_of(job)
    if not user_id or not client_id:
        return  # scheduled/background run, or no client context — nothing to ping
    supabase = get_supabase()
    # The in-memory `job` dict still carries the claimed status='running' — the
    # handler settled its own DB row without mutating it. Re-read the terminal
    # status/error so we notify on the true outcome (not the stale 'running').
    try:
        fresh = (
            supabase.table("async_jobs").select("status, error")
            .eq("id", job.get("id")).single().execute()
        ).data or {}
    except Exception:  # pragma: no cover — settled state unknowable → skip
        return
    note = single_job_notification(
        job_type, _lookup_client_name(supabase, client_id),
        fresh.get("status") or "", fresh.get("error"),
    )
    if not note:
        return
    desc = SINGLE_JOB_REGISTRY.get(job_type, {})
    path = desc.get("path")
    link = path.format(cid=client_id) if path else None
    notifications.emit(
        client_id=client_id,
        kind="task_complete",
        title=note["title"],
        summary=note["summary"],
        severity=note["severity"],
        payload={"job_type": job_type, "user_id": user_id, "link": link},
        dedupe_key=f"task_complete:{job.get('id')}",
        recipient_profile_id=user_id,
    )


def on_job_settled(job: dict) -> None:
    """Worker post-settle hook for every ACTIVITY_JOB_TYPES job: route a content
    page job to its batch-completion rollup, and a single registered job to its
    per-job completion ping. Best-effort — never raises into the worker."""
    try:
        if family_for(job.get("job_type")):
            on_content_job_settled(job)
        else:
            _on_single_job_settled(job)
    except Exception as exc:  # pragma: no cover - best effort
        logger.error("activity.on_job_settled_failed", extra={"job_id": job.get("id"), "error": str(exc)})


def _lookup_client_name(supabase, client_id: str) -> str:
    try:
        row = (
            supabase.table("clients").select("name").eq("id", client_id).single().execute()
        ).data
        return (row or {}).get("name") or "your client"
    except Exception:  # pragma: no cover
        return "your client"
