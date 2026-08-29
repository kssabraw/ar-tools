"""Client-facing "your content is ready" Slack pings (PACE).

When content finishes generating for a client — a Blog/Service Writer run, a
Local SEO page, an Ecommerce page, or a Website Builder page — PACE posts one
message in that client's own Slack channel (``clients.slack_channel_id``,
falling back to the master PACE channel — see ``services/notifications.py``)
via the ``content_ready`` notification kind.

A bulk operation (a multi-page bulk-create, a drip-release batch, several runs
queued through the Content Scheduler) settles into ONE summary message, not one
per item. The batch-detection shape mirrors the existing personal-bell rollup
in ``services/activity.py`` (last-in-flight-settles wins, race-free under
single-worker execution; a creation-time gap splits back-to-back batches), but
this ping is client-facing (no ``recipient_profile_id``) and is deliberately
NOT gated on ``payload.user_id`` — a scheduled/background generation (a drip
release, an auto-triggered regen) should tell the client's channel just as much
as an interactive one.

Deliberately CREATION only (``local_seo_generate``/``ecommerce_generate``/
``website_page_generate``/writer runs) — not reoptimize jobs. "Content is done
being created" is about new pages, not edits to existing ones.

Best-effort throughout: a failure here must never break the run/job it rides.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# async_jobs job_types this module pings on, and the label used in the message.
JOB_TYPES: dict[str, str] = {
    "local_seo_generate": "Local SEO",
    "ecommerce_generate": "Ecommerce",
    "website_page_generate": "Website",
}

# Blog/Service Writer runs are a separate table (``runs``), not async_jobs —
# handled by on_run_settled below, grouped under this label.
RUN_FAMILY = "runs"
RUN_LABEL = "Blog & Service"

_RUN_TERMINAL = ("complete", "failed", "cancelled")
_JOB_TERMINAL = ("complete", "failed")
_CANCELLED_ERROR = "cancelled_by_user"

# How far back to look when reconstructing "this batch" at settle time, and how
# large a creation-time gap starts a new batch (mirrors services/activity.py).
_BATCH_WINDOW_HOURS = 12
_BATCH_GAP_SECONDS = 300


# ----------------------------------------------------------------------------
# Pure helpers — unit-tested.
# ----------------------------------------------------------------------------
def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def latest_batch(rows: list[dict], gap_seconds: int = _BATCH_GAP_SECONDS) -> list[dict]:
    """Isolate the most recent contiguous batch from terminal rows (newest
    first by ``created_at``), splitting on a creation-time gap so an earlier
    batch in the same lookback window isn't merged in. Pure."""
    if not rows:
        return []
    parsed = [(ts, r) for r in rows if (ts := _parse_ts(r.get("created_at"))) is not None]
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


def summarize(rows: list[dict], *, cancelled_status: Optional[str] = None) -> dict[str, int]:
    """Count done / failed / cancelled over a batch's terminal rows. Pure.

    ``cancelled_status``: pass a row status value that itself marks
    cancellation (runs use a distinct ``'cancelled'`` status). Without it,
    cancellation is read off a ``'failed'`` row's ``error`` field (async_jobs'
    convention: ``error == 'cancelled_by_user'``)."""
    done = failed = cancelled = 0
    for r in rows:
        status = r.get("status")
        if status == "complete":
            done += 1
        elif cancelled_status and status == cancelled_status:
            cancelled += 1
        elif status == "failed":
            if (r.get("error") or "") == _CANCELLED_ERROR:
                cancelled += 1
            else:
                failed += 1
    return {"done": done, "failed": failed, "cancelled": cancelled, "total": done + failed + cancelled}


def build_note(label: str, client_name: str, counts: dict[str, int]) -> Optional[dict]:
    """{title, summary} for a finished content batch, or None when there's
    nothing worth announcing (everything in the batch was cancelled — the user
    already knows, they cancelled it). Pure."""
    done, failed = counts["done"], counts["failed"]
    if done == 0 and failed == 0:
        return None
    unit_singular = "article" if label == RUN_LABEL else "page"
    unit = unit_singular if (done + failed) == 1 else f"{unit_singular}s"
    parts = [f"{done} done"]
    if failed:
        parts.append(f"{failed} failed")
    if counts["cancelled"]:
        parts.append(f"{counts['cancelled']} cancelled")
    return {
        "title": f"{label} {unit} ready",
        "summary": f"{label} content for {client_name} finished — {', '.join(parts)}.",
    }


# ----------------------------------------------------------------------------
# Impure — DB reads + the notification emit.
# ----------------------------------------------------------------------------
def _client_name(supabase, client_id: str) -> str:
    try:
        row = supabase.table("clients").select("name").eq("id", client_id).single().execute().data
        return (row or {}).get("name") or "the client"
    except Exception:  # noqa: BLE001 — a display name is never worth failing over
        return "the client"


def _emit(client_id: str, family_key: str, label: str, link: str, counts: dict[str, int],
          stamp: str, client_name: str) -> None:
    note = build_note(label, client_name, counts)
    if not note:
        return
    notifications.emit(
        client_id=client_id,
        kind="content_ready",
        title=note["title"],
        summary=note["summary"],
        severity="info",
        payload={"family": family_key, "link": link, **counts},
        dedupe_key=f"content_ready:{client_id}:{family_key}:{stamp}",
    )


def on_job_settled(job: dict) -> None:
    """Called by the job worker after a ``JOB_TYPES`` async job reaches a
    terminal state. If it was the last in-flight job of its (client, job_type)
    group, post one summary message to the client's Slack channel.

    Grouped by ``job_type`` (not a broader family) so, e.g., a Local SEO
    bulk-create and an Ecommerce bulk-create settling around the same time post
    as two correctly-counted messages instead of one merged/misattributed one.
    Best-effort — never raises."""
    if not settings.content_ready_notifications_enabled:
        return
    try:
        job_type = job.get("job_type")
        label = JOB_TYPES.get(job_type or "")
        if not label:
            return
        payload = job.get("payload") or {}
        client_id = payload.get("client_id") or job.get("entity_id")
        if not client_id:
            return
        client_id = str(client_id)
        supabase = get_supabase()

        remaining = (
            supabase.table("async_jobs")
            .select("id", count="exact")
            .eq("job_type", job_type)
            .in_("status", ["pending", "running"])
            .eq("payload->>client_id", client_id)
            .execute()
        ).count or 0
        if remaining > 0:
            return  # batch still running

        window_start = (datetime.now(timezone.utc) - timedelta(hours=_BATCH_WINDOW_HOURS)).isoformat()
        terminal = (
            supabase.table("async_jobs")
            .select("id, status, error, created_at")
            .eq("job_type", job_type)
            .in_("status", list(_JOB_TERMINAL))
            .eq("payload->>client_id", client_id)
            .gte("completed_at", window_start)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
        batch = latest_batch(terminal)
        if not batch:
            return
        counts = summarize(batch)
        started = min(
            (ts for r in batch if (ts := _parse_ts(r.get("created_at"))) is not None), default=None
        )
        stamp = started.strftime("%Y%m%d%H%M") if started else "x"
        _emit(client_id, job_type, label, f"clients/{client_id}", counts, stamp,
              _client_name(supabase, client_id))
    except Exception as exc:  # pragma: no cover — best effort
        logger.error("content_ready.on_job_settled_failed", extra={"job_id": job.get("id"), "error": str(exc)})


def on_run_settled(run_id: str) -> None:
    """Called after a run (blog/service/location page) reaches a terminal
    status. Mirrors on_job_settled but reads the ``runs`` table, which has no
    async_jobs row of its own. Best-effort — never raises."""
    if not settings.content_ready_notifications_enabled:
        return
    try:
        supabase = get_supabase()
        row = (
            supabase.table("runs").select("id, client_id, status, created_at")
            .eq("id", run_id).single().execute()
        ).data
        if not row or not row.get("client_id") or row.get("status") not in _RUN_TERMINAL:
            return
        client_id = str(row["client_id"])

        remaining = (
            supabase.table("runs")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .not_.in_("status", list(_RUN_TERMINAL))
            .execute()
        ).count or 0
        if remaining > 0:
            return  # batch still running

        window_start = (datetime.now(timezone.utc) - timedelta(hours=_BATCH_WINDOW_HOURS)).isoformat()
        terminal = (
            supabase.table("runs")
            .select("id, status, created_at")
            .eq("client_id", client_id)
            .in_("status", list(_RUN_TERMINAL))
            .gte("completed_at", window_start)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
        batch = latest_batch(terminal)
        if not batch:
            return
        counts = summarize(batch, cancelled_status="cancelled")
        started = min(
            (ts for r in batch if (ts := _parse_ts(r.get("created_at"))) is not None), default=None
        )
        stamp = started.strftime("%Y%m%d%H%M") if started else "x"
        _emit(client_id, RUN_FAMILY, RUN_LABEL, f"clients/{client_id}/runs", counts, stamp,
              _client_name(supabase, client_id))
    except Exception as exc:  # pragma: no cover — best effort
        logger.error("content_ready.on_run_settled_failed", extra={"run_id": run_id, "error": str(exc)})
