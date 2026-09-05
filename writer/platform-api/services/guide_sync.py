"""DORA guide sync — keep each module's in-app guide current when the module changes.

The loop (owner ask 2026-09-02: "every time a module gets changes that affect
the user or output, DORA gets notified and updates the module's tutorial page
if needed"):

1. A change lands on ``main``. The CI reporter
   (``scripts/report_module_changes.py`` + ``.github/workflows/guide-sync.yml``)
   groups the changed files by module through ``services/guide_registry.py``,
   drops everything that can't be user-facing (tests, docs, CI, migrations…),
   and POSTs one entry per affected module — the user-facing file list, the
   commit messages, and a bounded unified diff — to
   ``POST /director/module-changes`` (bearer-secret guarded).
2. ``ingest_module_changes`` records ONE ``guide_sync_runs`` row per
   (commit, module) — the unique pair makes a re-delivered webhook a no-op —
   and enqueues a ``guide_sync`` async job per row.
3. ``process_run`` (the job) loads the module's guide (the ``guides`` row the
   Guides portal renders — DB-backed, the same page an admin edits in-app),
   hands DORA the guide + the change, and gets back a verdict: not user-visible
   (``no_change``, nothing written) or a full revised guide body. The rewrite
   must pass a deterministic sanity check (``validate_revision`` — size band,
   still a Markdown guide, actually different) before it can touch the guide.
4. With ``guide_sync_auto_apply`` (default on) the guide is rewritten in place
   and the PRIOR body is kept on the run for a one-click **Revert** from the
   guide page; with it off the rewrite waits as a ``proposed`` run an admin
   applies or dismisses. Either way one ``guide_sync`` notification goes to
   #dora naming the guide and what changed for users. A judged-not-needed
   review is silent (logged + on the run row, no Slack noise).

Scope note. DORA is otherwise read-only (the locked "eyes, not hands" framing).
This is its ONE write, and it is documentation, not operational state: it
never touches the board, the plans, or any precedence engine, and every
applied rewrite is reversible from the guide page. Gated on
``director_enabled`` + ``guide_sync_enabled``; fail-closed without a secret.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import guide_registry, guide_store

logger = logging.getLogger(__name__)

JOB_TYPE = "guide_sync"
NOTIFY_KIND = "guide_sync"
OPEN_STATUSES = ("queued", "running")
# Statuses a human can still act on from the guide page.
ACTIONABLE = {"applied": ("revert",), "proposed": ("apply", "dismiss")}

_REVIEW_TOOL = "emit_guide_review"
_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_update": {
            "type": "boolean",
            "description": "true only when the change alters what a user sees, does, or gets from the module.",
        },
        "reason": {
            "type": "string",
            "description": "One sentence: why the guide does / does not need to change.",
        },
        "change_summary": {
            "type": "string",
            "description": "1–3 plain sentences for the team: what changed for USERS. Empty when needs_update is false.",
        },
        "updated_body": {
            "type": "string",
            "description": "The FULL revised guide body (Markdown). Required when needs_update is true; omit otherwise.",
        },
        "updated_summary": {
            "type": "string",
            "description": "A revised one-line card summary, ONLY if the change made the current one inaccurate.",
        },
    },
    "required": ["needs_update", "reason"],
}

_REVIEW_SYSTEM = (
    "You are DORA — Director of Operations for an SEO agency's internal tool suite "
    "(AR Tools). One of your duties is keeping the team's in-app Guides current: every "
    "module has a guide written for a non-technical teammate — where the tool lives, "
    "what its options do, when to pick one over another, what it produces, and tips.\n\n"
    "You are handed the CURRENT guide for one module and a code change that just "
    "shipped to that module (commit messages, the files touched, and a diff). Decide "
    "whether the guide still describes the module accurately, and if not, rewrite it.\n\n"
    "WHEN TO UPDATE. Set needs_update=true ONLY when the change alters something a user "
    "would notice: a new, removed, or renamed option / button / tab / field / setting / "
    "step; a changed default, limit, cadence, or cost; a new or changed output (a report "
    "section, a column, a file, a notification); a behaviour the guide currently "
    "describes that is now different. Internal refactors, performance, logging, retries, "
    "test-only changes, error-handling that restores documented behaviour, and bug fixes "
    "that make the tool do what the guide ALREADY says → needs_update=false. When in "
    "doubt about whether a change is visible, it is not — prefer leaving a correct guide "
    "alone over rewriting it on a hunch.\n\n"
    "HOW TO UPDATE. Return the FULL revised guide body, not a fragment. Preserve the "
    "existing structure, headings, tone, and every section that is still true; change "
    "only what the diff justifies — a sentence or bullet where a new option belongs, a "
    "fix or removal where a statement became false. Keep the `# Title` line. Use only "
    "the guide's Markdown subset: `#`/`##`/`###` headings, **bold**, `-` bullets, pipe "
    "tables, `---` rules. Write for the teammate USING the tool: never mention code, "
    "file names, functions, PR or commit numbers, migrations, config flags, or "
    "environment variables — describe the tool the way it is experienced in the "
    "dashboard or Slack. Never invent behaviour the diff does not show. Do not grow the "
    "guide by more than roughly a quarter unless the change is genuinely that large.\n\n"
    "change_summary is a Slack note to the team: 1–3 plain sentences on what changed "
    "for users (what they can now do / no longer do / should expect). reason is one "
    "sentence justifying the verdict either way. Return updated_summary only if the "
    "guide's one-line card blurb is now inaccurate."
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def gate_open() -> bool:
    """Whether the sync runs at all: rides the DORA master gate."""
    return bool(settings.director_enabled and settings.guide_sync_enabled)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clip_text(text: Optional[str], limit: int) -> str:
    """Bound a diff/body for the prompt; marks the cut so the model knows."""
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[… truncated {len(text) - limit} characters …]"


def normalize_change(entry: dict) -> Optional[dict]:
    """Validate + normalize one module entry from the CI payload. Returns None
    for an entry that can't produce a run: the unmapped bucket, an unknown
    module, no user-facing files. The guide slug always comes from the
    registry (never trusted from the payload)."""
    if not isinstance(entry, dict):
        return None
    key = str(entry.get("module") or entry.get("module_key") or "").strip()
    if not key or key == guide_registry.UNMAPPED:
        return None
    slug = guide_registry.guide_slug_for(key)
    if not slug:
        return None
    files = [str(f).strip() for f in (entry.get("files") or []) if str(f).strip()]
    files = sorted({f for f in files if guide_registry.is_user_facing(f)})
    if not files:
        return None
    commits = []
    for c in entry.get("commits") or []:
        if not isinstance(c, dict):
            continue
        sha = str(c.get("sha") or "").strip()
        title = str(c.get("title") or c.get("message") or "").strip()
        if not (sha or title):
            continue
        commits.append({
            "sha": sha[:40],
            "title": title[:300],
            "body": str(c.get("body") or "").strip()[:4000],
        })
    return {
        "module_key": key,
        "module_label": guide_registry.module_label(key),
        "guide_slug": slug,
        "files": files,
        "diff": clip_text(entry.get("diff"), settings.guide_sync_diff_chars),
        "commits": commits[:25],
    }


def summarize_commits(commits: list[dict]) -> str:
    lines = []
    for c in commits or []:
        title = c.get("title") or "(no title)"
        sha = (c.get("sha") or "")[:7]
        lines.append(f"- {title}" + (f" ({sha})" if sha else ""))
        body = (c.get("body") or "").strip()
        if body:
            for ln in body.splitlines()[:12]:
                lines.append(f"    {ln.rstrip()}")
    return "\n".join(lines) or "- (no commit messages supplied)"


def build_review_prompt(guide: dict, run: dict) -> str:
    """The user turn for the review: module, guide, and the change."""
    parts = [
        f"MODULE: {run.get('module_label') or run.get('module_key')}",
        f"GUIDE TITLE: {guide.get('title') or ''}",
        f"GUIDE CARD SUMMARY: {guide.get('summary') or ''}",
        "CURRENT GUIDE BODY (Markdown):\n" + (guide.get("body") or ""),
        "COMMITS THAT SHIPPED:\n" + summarize_commits(run.get("commits") or []),
        "USER-FACING FILES TOUCHED:\n" + "\n".join(f"- {f}" for f in (run.get("files") or [])),
        "DIFF (unified; may be truncated):\n" + clip_text(run.get("diff"), settings.guide_sync_diff_chars),
        "Decide whether this guide still describes the module accurately, and emit your review.",
    ]
    return "\n\n".join(parts)


def validate_revision(prior_body: str, proposed_body: Optional[str],
                      *, min_ratio: Optional[float] = None,
                      max_ratio: Optional[float] = None) -> tuple[bool, Optional[str]]:
    """Deterministic sanity check on DORA's rewrite: present, still a Markdown
    guide (leads with a heading), within a size band of the prior body, and
    actually different. Returns (ok, reason)."""
    min_ratio = settings.guide_sync_min_ratio if min_ratio is None else min_ratio
    max_ratio = settings.guide_sync_max_ratio if max_ratio is None else max_ratio
    body = (proposed_body or "").strip()
    if not body:
        return False, "empty_body"
    if body.startswith("```"):
        return False, "fenced_body"
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if not first.startswith("#"):
        return False, "not_a_guide"
    prior = (prior_body or "").strip()
    if body == prior:
        return False, "identical"
    if prior:
        ratio = len(body) / max(len(prior), 1)
        if ratio < min_ratio:
            return False, f"too_short:{ratio:.2f}"
        if ratio > max_ratio:
            return False, f"too_long:{ratio:.2f}"
    return True, None


def notification_for(run: dict, guide_title: Optional[str]) -> Optional[dict]:
    """What (if anything) to tell #dora about a settled run. ``no_change`` is
    deliberately silent — DORA reviewed and found nothing user-visible, which
    is the common case and would be pure noise."""
    status = run.get("status")
    title = guide_title or run.get("guide_slug") or run.get("module_label") or "guide"
    commits = run.get("commits") or []
    after = f" after “{commits[0].get('title')}”" if commits and commits[0].get("title") else ""
    if status == "applied":
        return {
            "title": f"DORA updated the “{title}” guide",
            "summary": (run.get("change_summary") or run.get("reason") or "").strip()
            + f"\n\nUpdated{after}. Open the guide to read it; Revert is one click if it reads wrong.",
            "severity": "info",
        }
    if status == "proposed":
        return {
            "title": f"DORA proposes an update to the “{title}” guide",
            "summary": (run.get("change_summary") or run.get("reason") or "").strip()
            + f"\n\nProposed{after}. Review it on the guide page — Apply or Dismiss.",
            "severity": "info",
        }
    if status in ("rejected", "failed"):
        return {
            "title": f"DORA couldn't update the “{title}” guide",
            "summary": f"A module change{after} looked user-facing but the rewrite didn't go through "
                       f"({run.get('error') or run.get('reason') or status}). Check the guide by hand.",
            "severity": "warning",
        }
    if status == "no_guide":
        return {
            "title": f"No guide to update for {run.get('module_label') or run.get('module_key')}",
            "summary": f"A user-facing change shipped{after} but there is no guide with slug "
                       f"“{run.get('guide_slug')}” — create one in Guides so DORA can keep it current.",
            "severity": "info",
        }
    return None


# ---------------------------------------------------------------------------
# Ingest (the webhook side)
# ---------------------------------------------------------------------------
def ingest_module_changes(payload: dict) -> dict:
    """Record one run per (commit, module) and enqueue its review. Idempotent:
    a re-delivered payload skips rows that already exist. Returns counts +
    the accepted run ids."""
    sha = str((payload or {}).get("commit_sha") or "").strip()
    if not sha:
        return {"accepted": [], "skipped": 0, "error": "missing_commit_sha"}
    commit_range = str(payload.get("commit_range") or "").strip() or None
    supabase = get_supabase()
    accepted: list[dict] = []
    skipped = 0
    for raw in payload.get("changes") or []:
        change = normalize_change(raw)
        if not change:
            skipped += 1
            if isinstance(raw, dict) and (raw.get("module") == guide_registry.UNMAPPED):
                logger.info("guide_sync.unmapped_changes",
                            extra={"commit": sha[:7], "files": (raw.get("files") or [])[:20]})
            continue
        existing = (
            supabase.table("guide_sync_runs").select("id, status")
            .eq("commit_sha", sha).eq("module_key", change["module_key"])
            .limit(1).execute()
        ).data
        if existing:
            skipped += 1
            continue
        guide = guide_store.get_guide(change["guide_slug"])
        row = (
            supabase.table("guide_sync_runs").insert({
                "module_key": change["module_key"],
                "module_label": change["module_label"],
                "guide_slug": change["guide_slug"],
                "guide_id": (guide or {}).get("id"),
                "commit_sha": sha,
                "commit_range": commit_range,
                "commits": change["commits"],
                "files": change["files"],
                "diff": change["diff"],
                "status": "queued",
            }).execute()
        ).data[0]
        job_id = enqueue_guide_sync(row["id"])
        accepted.append({"run_id": row["id"], "module": change["module_key"],
                         "guide_slug": change["guide_slug"], "job_id": job_id})
    logger.info("guide_sync.ingested", extra={"commit": sha[:7], "accepted": len(accepted), "skipped": skipped})
    return {"accepted": accepted, "skipped": skipped}


def enqueue_guide_sync(run_id: str) -> Optional[str]:
    """One review job per run (deduped against an in-flight job for the same run)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", JOB_TYPE).eq("entity_id", run_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    row = (
        supabase.table("async_jobs").insert({
            "job_type": JOB_TYPE,
            "entity_id": run_id,
            "payload": {"run_id": run_id},
        }).execute()
    ).data[0]
    return row["id"]


# ---------------------------------------------------------------------------
# The review job
# ---------------------------------------------------------------------------
def _set_run(run_id: str, updates: dict) -> dict:
    updates = {**updates, "updated_at": _now_iso()}
    res = get_supabase().table("guide_sync_runs").update(updates).eq("id", run_id).execute()
    return (res.data or [{}])[0]


def _get_run(run_id: str) -> Optional[dict]:
    rows = get_supabase().table("guide_sync_runs").select("*").eq("id", run_id).limit(1).execute().data
    return rows[0] if rows else None


async def review_guide(guide: dict, run: dict) -> dict:
    """The one LLM call: DORA reads the guide + the change and emits its review."""
    from services import report_llm

    return await report_llm.run_forced_tool(
        provider="anthropic",
        model=settings.guide_sync_model,
        system=_REVIEW_SYSTEM,
        user=build_review_prompt(guide, run),
        tool_name=_REVIEW_TOOL,
        tool_description=(
            "Emit the guide review: whether the guide needs updating for this change and, "
            "when it does, the full revised guide body. Write updated_body before reason."
        ),
        input_schema=_REVIEW_SCHEMA,
        max_tokens=settings.guide_sync_max_tokens,
        log_tag="guide_sync",
    )


def _notify(run: dict, guide: Optional[dict]) -> Optional[str]:
    """Best-effort #dora notification for a settled run (deduped per run+status)."""
    note = notification_for(run, (guide or {}).get("title"))
    if not note:
        return None
    try:
        from services import notifications

        return notifications.emit(
            client_id=None, kind=NOTIFY_KIND,
            title=note["title"], summary=note["summary"], severity=note["severity"],
            payload={
                "link": f"/guides/{run.get('guide_slug')}" if run.get("guide_slug") else "/guides",
                "run_id": run.get("id"), "module": run.get("module_key"),
                "commit_sha": run.get("commit_sha"), "status": run.get("status"),
            },
            dedupe_key=f"guide_sync:{run.get('id')}:{run.get('status')}",
        )
    except Exception as exc:  # noqa: BLE001 — a notification failure never fails the run
        logger.warning("guide_sync.notify_failed", extra={"run_id": run.get("id"), "error": str(exc)})
        return None


async def process_run(run_id: str) -> dict:
    """Review one run end-to-end and settle its status. Returns the final row."""
    run = _get_run(run_id)
    if not run:
        return {"status": "missing", "id": run_id}
    if run.get("status") not in OPEN_STATUSES:
        return run  # already settled (a requeued job)
    _set_run(run_id, {"status": "running"})
    guide = guide_store.get_guide(run.get("guide_slug") or "") if run.get("guide_slug") else None
    if not guide:
        row = _set_run(run_id, {"status": "no_guide", "reason": "guide_missing"})
        _notify(row, None)
        return row
    try:
        review = await review_guide(guide, run) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("guide_sync.review_failed", extra={"run_id": run_id, "error": str(exc)})
        row = _set_run(run_id, {"status": "failed", "error": str(exc)[:500]})
        _notify(row, guide)
        return row

    needs = bool(review.get("needs_update"))
    reason = str(review.get("reason") or "").strip()[:1000]
    change_summary = str(review.get("change_summary") or "").strip()[:2000]
    if not needs:
        row = _set_run(run_id, {"status": "no_change", "needs_update": False, "reason": reason})
        logger.info("guide_sync.no_change", extra={"run_id": run_id, "guide": guide.get("slug")})
        return row

    proposed_body = (review.get("updated_body") or "").strip()
    ok, why = validate_revision(guide.get("body") or "", proposed_body)
    if not ok:
        if why == "identical":
            row = _set_run(run_id, {"status": "no_change", "needs_update": True, "reason": reason,
                                    "change_summary": change_summary, "error": "identical_body"})
            return row
        row = _set_run(run_id, {"status": "rejected", "needs_update": True, "reason": reason,
                                "change_summary": change_summary, "error": why,
                                "proposed_body": proposed_body[:200000]})
        _notify(row, guide)
        return row

    proposed_summary = (review.get("updated_summary") or "").strip()[:500] or None
    base = {
        "needs_update": True, "reason": reason, "change_summary": change_summary,
        "guide_id": guide.get("id"),
        "prior_body": guide.get("body") or "", "prior_summary": guide.get("summary") or "",
        "proposed_body": proposed_body, "proposed_summary": proposed_summary,
    }
    if settings.guide_sync_auto_apply:
        updates = {"body": proposed_body}
        if proposed_summary:
            updates["summary"] = proposed_summary
        guide_store.update_guide(guide["id"], updates)
        row = _set_run(run_id, {**base, "status": "applied", "applied_at": _now_iso()})
        logger.info("guide_sync.applied", extra={"run_id": run_id, "guide": guide.get("slug")})
    else:
        row = _set_run(run_id, {**base, "status": "proposed"})
        logger.info("guide_sync.proposed", extra={"run_id": run_id, "guide": guide.get("slug")})
    _notify(row, guide)
    return row


async def run_guide_sync_job(job: dict) -> None:
    """async_jobs handler for job_type='guide_sync'."""
    payload = job.get("payload") or {}
    run_id = payload.get("run_id") or job.get("entity_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not run_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing run_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    if not gate_open():
        # Dark: settle the run so it never lingers as queued, no LLM spend.
        _set_run(run_id, {"status": "dismissed", "reason": "guide_sync_disabled"})
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"status": "disabled"}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        row = await process_run(run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("guide_sync.job_failed", extra={"run_id": run_id, "error": str(exc)})
        try:
            _set_run(run_id, {"status": "failed", "error": str(exc)[:500]})
        except Exception:  # noqa: BLE001
            pass
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update({
        "status": "complete",
        "result": {"status": row.get("status"), "guide_slug": row.get("guide_slug"),
                   "reason": row.get("reason")},
        "completed_at": "now()",
    }).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Human decisions (the guide page)
# ---------------------------------------------------------------------------
def _require_run(run_id: str) -> dict:
    from fastapi import HTTPException

    run = _get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="guide_sync_run_not_found")
    return run


def _require_status(run: dict, *allowed: str) -> None:
    from fastapi import HTTPException

    if run.get("status") not in allowed:
        raise HTTPException(status_code=409, detail=f"guide_sync_run_{run.get('status')}")


def _guide_for_run(run: dict) -> dict:
    from fastapi import HTTPException

    guide = guide_store.get_guide(run.get("guide_slug") or "") if run.get("guide_slug") else None
    if not guide:
        raise HTTPException(status_code=404, detail="guide_not_found")
    return guide


def apply_run(run_id: str, decided_by: Optional[str] = None) -> dict:
    """Apply a ``proposed`` rewrite. The guide's CURRENT body is re-snapshotted
    as the revert target (it may have been hand-edited since the proposal)."""
    run = _require_run(run_id)
    _require_status(run, "proposed")
    guide = _guide_for_run(run)
    updates = {"body": run.get("proposed_body") or ""}
    if run.get("proposed_summary"):
        updates["summary"] = run["proposed_summary"]
    guide_store.update_guide(guide["id"], updates)
    return _set_run(run_id, {
        "status": "applied", "applied_at": _now_iso(), "decided_by": decided_by,
        "prior_body": guide.get("body") or "", "prior_summary": guide.get("summary") or "",
        "guide_id": guide.get("id"),
    })


def revert_run(run_id: str, decided_by: Optional[str] = None) -> dict:
    """Restore the guide to the body it had before an ``applied`` rewrite."""
    run = _require_run(run_id)
    _require_status(run, "applied")
    guide = _guide_for_run(run)
    guide_store.update_guide(guide["id"], {
        "body": run.get("prior_body") or "",
        "summary": run.get("prior_summary") if run.get("prior_summary") is not None else (guide.get("summary") or ""),
    })
    return _set_run(run_id, {"status": "reverted", "reverted_at": _now_iso(), "decided_by": decided_by})


def dismiss_run(run_id: str, decided_by: Optional[str] = None) -> dict:
    run = _require_run(run_id)
    _require_status(run, "proposed", "rejected", "failed")
    return _set_run(run_id, {"status": "dismissed", "decided_by": decided_by})


_LIST_COLUMNS = (
    "id, module_key, module_label, guide_slug, guide_id, commit_sha, commit_range, commits, files, "
    "status, needs_update, reason, change_summary, proposed_summary, error, applied_at, reverted_at, "
    "decided_by, created_at, updated_at"
)


def list_runs(guide_slug: str, limit: int = 20, include_bodies: bool = False) -> list[dict]:
    """A guide's sync history, newest first. Bodies (prior/proposed) are large
    and only needed to preview a proposal — opt in."""
    cols = _LIST_COLUMNS + (", prior_body, proposed_body" if include_bodies else "")
    return (
        get_supabase().table("guide_sync_runs").select(cols)
        .eq("guide_slug", guide_slug).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_run(run_id: str) -> Optional[dict]:
    return _get_run(run_id)


# ---------------------------------------------------------------------------
# DORA read-model provider (portfolio-only; no seam, no task)
# ---------------------------------------------------------------------------
def recent_activity(supabase, today: Optional[date] = None, days: Optional[int] = None) -> Optional[dict]:
    """What DORA did to the guides recently — counts by status, open proposals,
    and the latest runs — so it can answer "which guides did you update and
    why". None when nothing ran in the window (the block is then omitted)."""
    if not settings.guide_sync_enabled:
        return None
    today = today or date.today()
    days = days or settings.guide_sync_recent_days
    cutoff = (today - timedelta(days=days)).isoformat()
    rows = (
        supabase.table("guide_sync_runs")
        .select("id, module_label, guide_slug, status, change_summary, reason, commits, created_at")
        .gte("created_at", cutoff).order("created_at", desc=True).limit(200).execute()
    ).data or []
    if not rows:
        return None
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status") or "unknown"] = by_status.get(r.get("status") or "unknown", 0) + 1

    def _brief(r: dict) -> dict:
        commits = r.get("commits") or []
        return {
            "run_id": r.get("id"), "guide_slug": r.get("guide_slug"),
            "module": r.get("module_label"), "status": r.get("status"),
            "what_changed": r.get("change_summary") or r.get("reason"),
            "commit": (commits[0].get("title") if commits else None),
            "at": r.get("created_at"),
        }

    return {
        "window_days": days,
        "runs": len(rows),
        "by_status": by_status,
        "open_proposals": [_brief(r) for r in rows if r.get("status") == "proposed"][:10],
        "recent": [_brief(r) for r in rows if r.get("status") in ("applied", "reverted", "rejected", "failed", "no_guide")][:15],
        "auto_apply": bool(settings.guide_sync_auto_apply),
    }
