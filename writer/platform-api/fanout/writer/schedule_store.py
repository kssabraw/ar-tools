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
    location_code: int | None = None, auto_publish: bool = False,
    wp_publish: bool = False, wp_status: str = "draft",
    weekday: int | None = None, weekdays: list[int] | None = None,
    day_of_month: int | None = None, week_of_month: int | None = None,
) -> dict:
    """Insert the parent schedule + one queued run per planned cluster. Returns the parent
    row augmented with `run_count`. (Two statements — PostgREST has no multi-table txn; the
    children reference the parent id, and a failed child insert leaves an empty schedule that
    the worker simply never advances.)

    `content_type` selects the generator the worker uses per run ('blog_post' -> the Fanout
    writer; 'local_seo_page' -> the suite's nlp-api Local SEO generator). For local SEO the
    schedule also carries the target `location` (+ optional DataForSEO `location_code`).
    `wp_publish`/`wp_status` opt finished blog posts into the client's WordPress site
    (as 'draft' or live 'publish')."""
    client = get_service_client()
    parent = client.table("content_schedules").insert({
        "session_id": session_id, "user_id": user_id, "mode": mode,
        "per_day": per_day,
        "start_date": start_date.isoformat() if start_date else None,
        "time_of_day": time_of_day.isoformat() if time_of_day else "09:00",
        "timezone": tz_name, "total_count": len(runs),
        "content_type": content_type, "location": location,
        "location_code": location_code, "auto_publish": auto_publish,
        "wp_publish": wp_publish, "wp_status": wp_status,
        "weekday": weekday, "weekdays": weekdays,
        "day_of_month": day_of_month, "week_of_month": week_of_month,
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


def get_run(run_id: str) -> dict | None:
    res = (get_service_client().table("scheduled_article_runs").select("*")
           .eq("id", run_id).limit(1).execute())
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


def queued_runs_ordered(schedule_id: str) -> list[dict]:
    """The schedule's still-queued runs, in their planned order (by scheduled_at).
    These are the articles a cadence change re-times — completed/running ones are
    left alone. Paged above the ~1000-row read cap."""
    client = get_service_client()
    out: list[dict] = []
    page = 0
    while True:
        rows = (client.table("scheduled_article_runs").select("id, cluster_id, scheduled_at")
                .eq("content_schedule_id", schedule_id).eq("status", "queued")
                .order("scheduled_at").order("id")
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.extend(rows)
        if len(rows) < 1000:
            return out
        page += 1


def apply_reschedule(queued_runs: list[dict], planned_runs: list) -> int:
    """Re-time queued runs to `planned_runs` (positionally — plan_runs preserves input
    order). Groups runs sharing a target datetime into one update, so the write cost is
    ~one call per distinct period, not per article. Still filtered on status='queued' so
    a run the worker claimed between read and write is never stomped. Returns runs touched."""
    from collections import defaultdict

    client = get_service_client()
    groups: dict[str, list[str]] = defaultdict(list)
    for run, planned in zip(queued_runs, planned_runs):
        groups[planned.scheduled_at.isoformat()].append(run["id"])
    touched = 0
    for iso, ids in groups.items():
        for start in range(0, len(ids), 200):
            res = (client.table("scheduled_article_runs").update({"scheduled_at": iso})
                   .in_("id", ids[start:start + 200]).eq("status", "queued").execute())
            touched += len(res.data or [])
    return touched


def update_schedule_fields(schedule_id: str, fields: dict) -> dict | None:
    """Patch arbitrary columns on a schedule (used for mid-run publish-target edits:
    auto_publish / wp_publish / wp_status). Returns the updated row. The worker reads
    these live per article, so a change applies to every run not yet generated."""
    if not fields:
        return get_schedule(schedule_id)
    res = (get_service_client().table("content_schedules")
           .update(fields).eq("id", schedule_id).execute())
    return res.data[0] if res.data else None


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


def cancel_run(run_id: str) -> bool:
    """Cancel a single still-queued run, leaving the rest of its schedule intact. The update is
    conditional on `status = 'queued'`, so it no-ops (returns False) if the worker has already
    claimed the run (running) or it has otherwise moved on — too late to stop it."""
    res = (get_service_client().table("scheduled_article_runs")
           .update({"status": "cancelled"})
           .eq("id", run_id).eq("status", "queued").execute())
    return bool(res.data)


def reinstate_run(run_id: str) -> bool:
    """Un-cancel a run (cancelled -> queued), clearing its prior started/completed/
    error state. Conditional on status='cancelled' so it can't resurrect a
    complete/failed row. Returns whether it flipped."""
    res = (get_service_client().table("scheduled_article_runs")
           .update({"status": "queued", "started_at": None,
                    "completed_at": None, "error": None})
           .eq("id", run_id).eq("status", "cancelled").execute())
    return bool(res.data)


def retry_failed_run(run_id: str) -> bool:
    """Manually requeue a single dead-lettered run (failed -> queued), resetting
    its attempt budget and clearing prior started/completed/error state, and
    making it due now (`scheduled_at = now()`). Conditional on status='failed' so
    it can't disturb a queued/running/complete/cancelled row. Returns whether it
    flipped."""
    from datetime import datetime, timezone

    res = (get_service_client().table("scheduled_article_runs")
           .update({"status": "queued", "attempts": 0, "started_at": None,
                    "completed_at": None, "error": None,
                    "scheduled_at": datetime.now(timezone.utc).isoformat()})
           .eq("id", run_id).eq("status", "failed").execute())
    return bool(res.data)


def retry_failed_runs(schedule_id: str) -> int:
    """Manually requeue every dead-lettered run in a schedule (failed -> queued,
    due now, attempts reset). Returns how many flipped. Paged conditional updates
    keep it correct above the ~1000-row cap while staying filtered to failed
    rows so nothing else is disturbed."""
    from datetime import datetime, timezone

    client = get_service_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    total = 0
    while True:
        ids = [r["id"] for r in (client.table("scheduled_article_runs").select("id")
               .eq("content_schedule_id", schedule_id).eq("status", "failed")
               .limit(500).execute().data or [])]
        if not ids:
            return total
        res = (client.table("scheduled_article_runs")
               .update({"status": "queued", "attempts": 0, "started_at": None,
                        "completed_at": None, "error": None, "scheduled_at": now_iso})
               .in_("id", ids).eq("status", "failed").execute())
        touched = len(res.data or [])
        total += touched
        if touched == 0:
            return total


def reflow_queued(schedule_id: str) -> int:
    """Re-pack a schedule's still-queued runs densely onto its cadence slots, from the
    earliest *available* slot — so cancelling articles (even the soonest ones) pulls the
    rest UP to reclaim the freed days, not merely closes interior gaps. No-op for
    all_at_once / fixed (no timeline gaps) and for a drained schedule. Returns runs re-timed.

    The re-flow start is the schedule's own cadence grid clamped to `max(start_date, today,
    day-after-the-last-written/running-slot)` — never the past, never colliding with an
    already-consumed slot, but as early as legitimately possible. Uses the cadence anchors
    persisted on the schedule; completed/running runs are untouched (apply_reschedule filters
    to status='queued')."""
    from datetime import date as _date
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from fanout.writer.schedule_planner import plan_runs

    sched = get_schedule(schedule_id)
    if not sched or sched.get("mode") in ("all_at_once", "fixed"):
        return 0
    queued = queued_runs_ordered(schedule_id)
    if not queued:
        return 0
    tz_name = sched.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — unknown tz: leave the queue as-is
        return 0
    today = datetime.now(tz).date()
    # Don't schedule before the schedule's own start, before today, or onto/into a slot
    # already taken by a written/writing article (start the day after the last such one).
    floor = today
    sched_start = sched.get("start_date")
    if sched_start:
        try:
            floor = max(floor, _date.fromisoformat(str(sched_start)))
        except ValueError:
            pass
    consumed = (get_service_client().table("scheduled_article_runs")
                .select("scheduled_at").eq("content_schedule_id", schedule_id)
                .in_("status", ["complete", "running"])
                .order("scheduled_at", desc=True).limit(1).execute().data or [])
    if consumed:
        try:
            last = datetime.fromisoformat(consumed[0]["scheduled_at"]).astimezone(tz).date()
            floor = max(floor, last + timedelta(days=1))
        except Exception:  # noqa: BLE001
            pass
    tod = _time_from(sched.get("time_of_day"))
    try:
        planned = plan_runs(
            [r["cluster_id"] for r in queued], mode=sched["mode"],
            per_day=sched.get("per_day"), start_date=floor, time_of_day=tod,
            tz_name=tz_name, weekday=sched.get("weekday"), weekdays=sched.get("weekdays"),
            day_of_month=sched.get("day_of_month"), week_of_month=sched.get("week_of_month"),
        )
    except Exception:  # noqa: BLE001 — never let a re-pack failure break cancel/reinstate
        return 0
    return apply_reschedule(queued, planned)


def _time_from(value):
    """Parse a stored time_of_day ('09:00:00' / '09:00') into a datetime.time; None -> 09:00."""
    from datetime import time as _t

    if not value:
        return _t(9, 0)
    try:
        return _t.fromisoformat(str(value))
    except ValueError:
        return _t(9, 0)


def complete_if_drained(schedule_id: str) -> None:
    """Mirror the worker's auto-complete: if an active schedule has no queued/running runs left,
    flip it to `complete`. Called after an API cancel of a single run so cancelling the last
    pending one settles the parent instead of leaving it stuck `active`."""
    client = get_service_client()
    pending = (client.table("scheduled_article_runs").select("id")
               .eq("content_schedule_id", schedule_id)
               .in_("status", ["queued", "running"]).limit(1).execute().data or [])
    if pending:
        return
    sched = get_schedule(schedule_id)
    if sched and sched["status"] == "active":
        set_schedule_status(schedule_id, "complete")
