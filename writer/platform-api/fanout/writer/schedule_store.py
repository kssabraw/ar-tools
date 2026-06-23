"""M15 slice 3 — content-schedule persistence (`fanout.content_schedules` +
`scheduled_article_runs`). Service-role reads/writes; the API is RLS-scoped to a visible
session. The worker (slice 4) claims due rows via the `claim_scheduled_runs` RPC."""

from __future__ import annotations

from datetime import date, time

from fanout.storage.supabase_client import get_service_client
from fanout.writer.schedule_planner import PlannedRun


def create_schedule(
    *, session_id: str, user_id: str, mode: str, runs: list[PlannedRun],
    per_day: int | None = None, start_date: date | None = None,
    time_of_day: time | None = None, tz_name: str = "UTC",
    content_type: str = "blog_post", location: str | None = None,
    location_code: int | None = None,
) -> dict:
    """Insert the parent schedule + one queued run per planned cluster. Returns the parent
    row augmented with `run_count`. (Two statements — PostgREST has no multi-table txn; the
    children reference the parent id, and a failed child insert leaves an empty schedule that
    the worker simply never advances.)

    `content_type` selects the generator the worker uses per run ('blog_post' -> the Fanout
    writer; 'local_seo_page' -> the suite's nlp-api Local SEO generator). For local SEO the
    schedule also carries the target `location` (+ optional DataForSEO `location_code`)."""
    client = get_service_client()
    parent = client.table("content_schedules").insert({
        "session_id": session_id, "user_id": user_id, "mode": mode,
        "per_day": per_day,
        "start_date": start_date.isoformat() if start_date else None,
        "time_of_day": time_of_day.isoformat() if time_of_day else "09:00",
        "timezone": tz_name, "total_count": len(runs),
        "content_type": content_type, "location": location,
        "location_code": location_code,
    }).execute().data[0]

    rows = [{
        "content_schedule_id": parent["id"], "cluster_id": r.cluster_id,
        "session_id": session_id, "user_id": user_id,
        "scheduled_at": r.scheduled_at.isoformat(), "status": "queued",
    } for r in runs]
    for start in range(0, len(rows), 500):                  # stay under PostgREST's row cap
        client.table("scheduled_article_runs").insert(rows[start:start + 500]).execute()
    parent["run_count"] = len(rows)
    return parent


def list_schedules(session_id: str | None = None) -> list[dict]:
    q = get_service_client().table("content_schedules").select("*")
    if session_id:
        q = q.eq("session_id", session_id)
    return q.order("created_at", desc=True).execute().data or []


def get_schedule(schedule_id: str) -> dict | None:
    res = (get_service_client().table("content_schedules").select("*")
           .eq("id", schedule_id).limit(1).execute())
    return res.data[0] if res.data else None


_STATUSES = ("queued", "running", "complete", "failed", "cancelled")


def progress_by_schedule(session_id: str) -> dict[str, dict]:
    """Per-schedule status counts for every schedule in a session, in one paged scan (avoids
    the N+1 of calling schedule_progress per row). {schedule_id: {queued,…,total}}."""
    client = get_service_client()
    agg: dict[str, dict] = {}
    page = 0
    while True:
        rows = (client.table("scheduled_article_runs").select("content_schedule_id, status")
                .eq("session_id", session_id)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        for r in rows:
            sid = r["content_schedule_id"]
            if sid is None:
                continue
            counts = agg.setdefault(sid, {s: 0 for s in _STATUSES} | {"total": 0})
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            counts["total"] += 1
        if len(rows) < 1000:
            return agg
        page += 1


def pending_cluster_ids(session_id: str) -> set[str]:
    """Clusters that already have a queued/running run in this session — so a new schedule
    doesn't double-book (and double-write) them. Paged so the guard stays complete above the
    ~1000-row read cap."""
    client = get_service_client()
    out: set[str] = set()
    page = 0
    while True:
        rows = (client.table("scheduled_article_runs").select("cluster_id")
                .eq("session_id", session_id).in_("status", ["queued", "running"])
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.update(r["cluster_id"] for r in rows)
        if len(rows) < 1000:
            return out
        page += 1


def list_runs(session_id: str, *, limit: int = 2000) -> list[dict]:
    """Runs for a session, paged up to `limit` (the overview table; newest schedules first
    via scheduled_at)."""
    client = get_service_client()
    out: list[dict] = []
    page = 0
    while len(out) < limit:
        rows = (client.table("scheduled_article_runs").select("*")
                .eq("session_id", session_id).order("scheduled_at", desc=False)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.extend(rows)
        if len(rows) < 1000:
            break
        page += 1
    return out[:limit]


def set_schedule_status(schedule_id: str, status: str) -> None:
    get_service_client().table("content_schedules").update({"status": status}).eq(
        "id", schedule_id).execute()


def cancel_schedule(schedule_id: str) -> int:
    """Cancel a schedule + all its still-pending (queued/running) runs. Returns runs cancelled.
    Completed/failed runs are left as historical record."""
    client = get_service_client()
    set_schedule_status(schedule_id, "cancelled")
    res = (client.table("scheduled_article_runs")
           .update({"status": "cancelled"})
           .eq("content_schedule_id", schedule_id)
           .in_("status", ["queued", "running"]).execute())
    return len(res.data or [])
