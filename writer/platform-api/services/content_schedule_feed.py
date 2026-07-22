"""Unified "Scheduled Content" feed — the per-client view that shows everything
queued across the suite, including Fanout.

Two sources, normalized to one row shape:
  - the suite Content Scheduler (`content_batches`, this module's own store), and
  - the Fanout content scheduler (`fanout.content_schedules` whose session is
    linked to this client).

The suite reaches the Fanout tables through Fanout's own service-role client
(scoped to the `fanout` schema); a failure there degrades to suite-only rather
than breaking the card. Read-only aggregation — no writes, no generation.
"""

from __future__ import annotations

import logging
from typing import Optional

from services import content_schedule_store as store

logger = logging.getLogger(__name__)

_ALL_BUCKETS = ("scheduled", "queued", "running", "complete", "failed", "cancelled")


def _norm_progress(raw: Optional[dict]) -> dict:
    p = {b: int((raw or {}).get(b, 0)) for b in _ALL_BUCKETS}
    p["total"] = int((raw or {}).get("total", sum(p.values())))
    return p


def _suite_rows(client_id: str) -> list[dict]:
    batches = store.list_batches(client_id)
    progress = store.progress_by_batch(client_id)
    rows = []
    for b in batches:
        rows.append({
            "source": "content_scheduler",
            "id": b["id"],
            "content_type": b["content_type"],
            "label": None,                       # a batch has no single keyword
            "mode": b["mode"],
            "status": b["status"],
            "created_at": b["created_at"],
            "github_publish": bool(b.get("github_publish")),
            "progress": _norm_progress(progress.get(b["id"])),
        })
    return rows


def _fanout_rows(client_id: str) -> list[dict]:
    """Fanout content schedules for this client's linked sessions. Best-effort:
    any failure (fanout schema not exposed, client never used Fanout) returns []
    so the card still renders the suite rows."""
    try:
        from fanout.storage.supabase_client import get_service_client
        from fanout.writer import schedule_store as fanout_store

        client = get_service_client()
        sessions = (client.table("sessions").select("id, seed_keyword")
                    .eq("client_id", client_id).execute().data or [])
        if not sessions:
            return []
        label_by_session = {s["id"]: s.get("seed_keyword") for s in sessions}
        session_ids = list(label_by_session)
        schedules = (client.table("content_schedules").select("*")
                     .in_("session_id", session_ids).execute().data or [])
        if not schedules:
            return []
        # Merge per-session progress maps ({schedule_id: counts}) into one lookup.
        progress: dict[str, dict] = {}
        for sid in session_ids:
            progress.update(fanout_store.progress_by_schedule(sid))
        rows = []
        for sch in schedules:
            rows.append({
                "source": "fanout",
                "id": sch["id"],
                "content_type": sch.get("content_type") or "blog_post",
                "label": label_by_session.get(sch.get("session_id")),
                "mode": sch.get("mode"),
                "status": sch.get("status"),
                "created_at": sch.get("created_at"),
                "progress": _norm_progress(progress.get(sch["id"])),
            })
        return rows
    except Exception as exc:  # noqa: BLE001 — the Fanout half is additive; degrade cleanly
        logger.warning("content_schedule_feed.fanout_read_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        return []


def unified_feed(client_id: str) -> list[dict]:
    """All scheduled content for a client — suite batches + client-linked Fanout
    schedules — newest first."""
    rows = _suite_rows(client_id) + _fanout_rows(client_id)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows
