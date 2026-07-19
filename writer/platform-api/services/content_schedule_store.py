"""Content Scheduler — persistence + pure planning for suite-wide bulk page
creation and scheduling (`content_batches` + `content_batch_items`).

The suite-native analogue of the Fanout content scheduler: a per-client,
content-type-scoped batch of keywords that either generates now or drips/weekly/
monthly-schedules out. It reuses the shared scheduler (`services/gsc_scheduler`)
+ `async_jobs` + `job_worker` rather than Fanout's session/cluster-bound
`scheduled_article_runs`, so it works from any content card without a
keyword-research session.

Cadence math is delegated to Fanout's PURE `schedule_planner.plan_runs` (imported,
not re-implemented) so scheduling behaviour is identical across the two systems.
The pure helpers here (normalize / plan / estimate) carry no DB and are unit
tested; the DB helpers use the service-role client like the rest of platform-api.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db.supabase_client import get_supabase
from fanout.writer.schedule_planner import ScheduleError, plan_runs

CONTENT_TYPES = ("blog_post", "service_page", "location_page", "local_seo_page",
                 "ecommerce")

# Per-content-type cost estimate ($/page) — the deliberate fix for the Fanout
# scheduler's known caveat of estimating every type at the blog constant. These
# are defaults; the router overrides them from settings.
DEFAULT_COST_PER_TYPE: dict[str, float] = {
    "blog_post": 0.75,
    "service_page": 0.60,
    "location_page": 0.60,
    "local_seo_page": 0.90,
    "ecommerce": 0.90,
}

_MAX_KEYWORD_LEN = 200
_STATUSES = ("scheduled", "queued", "running", "complete", "failed", "cancelled")


@dataclass
class BatchItemInput:
    """One requested page. `keyword` is the head term; the rest are per-row params
    (Option B) so a single upload can mix locations and per-page service sets."""

    keyword: str
    location: Optional[str] = None
    location_code: Optional[int] = None
    services: list[str] = field(default_factory=list)
    page_template_url: Optional[str] = None
    # Per-row free-text writing guidance (CSV "Notes" column). Fed into
    # generation for every content type — not just stored.
    notes: Optional[str] = None
    # Per-row publish date (CSV "Date" column). When set it overrides the batch
    # cadence for this row (generate + publish on this date at the batch
    # time-of-day). None -> follow the cadence / create-now.
    scheduled_date: Optional[date] = None


# ── pure helpers (no DB — unit tested) ───────────────────────────────────────


def _coerce_date(value) -> Optional[date]:
    """Accept a date, an ISO 'YYYY-MM-DD' string, or None. Anything unparseable
    (a typo) becomes None so the row falls back to the batch cadence rather than
    corrupting the calendar."""
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value if isinstance(value, date) else None
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def combine_local_date(
    d: date, tod: Optional[time], tz_name: str = "UTC"
) -> datetime:
    """The tz-aware UTC release datetime for an explicit per-row publish date at
    the batch time-of-day, interpreted in the batch timezone. Falls back to UTC
    for an unknown timezone name."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        tz = timezone.utc
    local = datetime.combine(d, tod or time(9, 0)).replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def _clean_services(raw) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in raw or []:
        v = (s or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def normalize_items(
    raw_items: list[dict | BatchItemInput], *, max_items: int
) -> tuple[list[BatchItemInput], int]:
    """Trim, drop blank / over-length keywords, de-dupe (case-insensitive on the
    keyword+location pair — the same keyword in two areas is two distinct pages),
    and cap at `max_items`. Returns (items, skipped) where skipped counts rows
    dropped as blank/dupe/over-length (NOT the over-cap remainder, which raises in
    the caller). Order is preserved."""
    seen: set[tuple[str, str]] = set()
    items: list[BatchItemInput] = []
    for raw in raw_items:
        it = raw if isinstance(raw, BatchItemInput) else BatchItemInput(
            keyword=(raw.get("keyword") or ""),
            location=(raw.get("location") or None),
            location_code=raw.get("location_code"),
            services=_clean_services(raw.get("services")),
            page_template_url=(raw.get("page_template_url") or None),
            notes=(raw.get("notes") or None),
        )
        kw = (it.keyword or "").strip()
        loc = (it.location or "").strip() or None
        key = (kw.lower(), (loc or "").lower())
        if not kw or len(kw) > _MAX_KEYWORD_LEN or key in seen:
            continue
        seen.add(key)
        items.append(BatchItemInput(
            keyword=kw, location=loc, location_code=it.location_code,
            services=_clean_services(it.services), page_template_url=it.page_template_url,
            notes=(it.notes or "").strip() or None,
            scheduled_date=_coerce_date(
                raw.get("scheduled_date") if isinstance(raw, dict) else it.scheduled_date
            ),
        ))
    skipped = len(raw_items) - len(items)
    return items[:max_items], skipped


def plan_item_datetimes(
    n: int, *, mode: str, per_day: Optional[int] = None,
    start_date: Optional[date] = None, time_of_day: Optional[time] = None,
    tz_name: str = "UTC", weekday: Optional[int] = None,
    weekdays: Optional[list[int]] = None, day_of_month: Optional[int] = None,
    week_of_month: Optional[int] = None, now_utc: Optional[datetime] = None,
) -> list[datetime]:
    """The release datetime (tz-aware UTC) for each of `n` items in order. `now`
    mode releases everything immediately; every other mode delegates to the
    reused Fanout planner (opaque ids -> scheduled_at). Raises ScheduleError on
    bad cadence params."""
    if n <= 0:
        return []
    now = now_utc or datetime.now(timezone.utc)
    if mode == "now":
        return [now] * n
    planned = plan_runs(
        [str(i) for i in range(n)], mode=mode, per_day=per_day, start_date=start_date,
        time_of_day=time_of_day, tz_name=tz_name, weekday=weekday, weekdays=weekdays,
        day_of_month=day_of_month, week_of_month=week_of_month, now_utc=now,
    )
    return [p.scheduled_at for p in planned]


def estimate_batch(
    count: int, content_type: str, mode: str, *,
    cost_per_type: Optional[dict[str, float]] = None,
    per_day: Optional[int] = None, start_date: Optional[date] = None,
    time_of_day: Optional[time] = None, tz_name: str = "UTC",
    weekday: Optional[int] = None, weekdays: Optional[list[int]] = None,
    day_of_month: Optional[int] = None, week_of_month: Optional[int] = None,
    now_utc: Optional[datetime] = None, explicit_finish: Optional[date] = None,
) -> dict:
    """Preview a batch without creating it: item count, per-content-type cost, and
    the finish date (the last release date). Best-effort on the finish date — a bad
    cadence just omits it (create validates for real). `explicit_finish` is the
    latest per-row publish Date across the batch; the finish date is the later of
    the cadence's last slot and that, so a dated row beyond the cadence horizon (or
    a dated create-now batch) is reflected in the preview."""
    costs = cost_per_type or DEFAULT_COST_PER_TYPE
    cost = round(count * costs.get(content_type, DEFAULT_COST_PER_TYPE["blog_post"]), 2)
    out: dict = {"count": count, "cost_estimate_usd": cost,
                 "content_type": content_type, "mode": mode}
    finish: Optional[date] = None
    if count and mode not in ("now", "all_at_once"):
        try:
            dts = plan_item_datetimes(
                count, mode=mode, per_day=per_day, start_date=start_date,
                time_of_day=time_of_day, tz_name=tz_name, weekday=weekday,
                weekdays=weekdays, day_of_month=day_of_month,
                week_of_month=week_of_month, now_utc=now_utc,
            )
            if dts:
                finish = dts[-1].date()
        except ScheduleError:
            pass
    if explicit_finish and (finish is None or explicit_finish > finish):
        finish = explicit_finish
    if finish:
        out["finish_date"] = finish.isoformat()
    return out


# ── DB helpers (service role) ────────────────────────────────────────────────


def create_batch(
    *, client_id: str, created_by: Optional[str], content_type: str, mode: str,
    items: list[BatchItemInput], per_day: Optional[int] = None,
    start_date: Optional[date] = None, time_of_day: Optional[time] = None,
    tz_name: str = "UTC", weekday: Optional[int] = None,
    weekdays: Optional[list[int]] = None, day_of_month: Optional[int] = None,
    week_of_month: Optional[int] = None, auto_publish: bool = False,
    wp_publish: bool = False, wp_status: str = "draft",
    now_utc: Optional[datetime] = None,
) -> dict:
    """Insert the parent batch + one scheduled item per input (release times from
    the planner). Items land status='scheduled'; the caller enqueues immediately
    for `mode='now'` (via services.content_batch.enqueue_items) or lets the shared
    scheduler release them when due. Returns the parent row with its `items`."""
    dts = plan_item_datetimes(
        len(items), mode=mode, per_day=per_day, start_date=start_date,
        time_of_day=time_of_day, tz_name=tz_name, weekday=weekday, weekdays=weekdays,
        day_of_month=day_of_month, week_of_month=week_of_month, now_utc=now_utc,
    )
    # A per-row explicit publish date overrides the cadence slot for that row
    # (generate + publish that day at the batch time-of-day, in the batch tz).
    dts = [
        combine_local_date(it.scheduled_date, time_of_day, tz_name)
        if it.scheduled_date else dt
        for it, dt in zip(items, dts)
    ]
    client = get_supabase()
    parent = client.table("content_batches").insert({
        "client_id": client_id, "created_by": created_by,
        "content_type": content_type, "mode": mode, "per_day": per_day,
        "weekday": weekday, "weekdays": weekdays, "day_of_month": day_of_month,
        "week_of_month": week_of_month,
        "start_date": start_date.isoformat() if start_date else None,
        "time_of_day": (time_of_day or time(9, 0)).isoformat(), "timezone": tz_name,
        "auto_publish": auto_publish, "wp_publish": wp_publish, "wp_status": wp_status,
        "status": "active", "total_count": len(items),
    }).execute().data[0]

    rows = [{
        "batch_id": parent["id"], "client_id": client_id, "keyword": it.keyword,
        "location": it.location, "location_code": it.location_code,
        "services": it.services, "page_template_url": it.page_template_url,
        "notes": it.notes,
        "scheduled_at": dt.isoformat(), "status": "scheduled",
    } for it, dt in zip(items, dts)]
    inserted: list[dict] = []
    for start in range(0, len(rows), 500):                  # PostgREST row cap
        res = client.table("content_batch_items").insert(rows[start:start + 500]).execute()
        inserted.extend(res.data or [])
    parent["items"] = inserted
    return parent


def get_batch(batch_id: str) -> Optional[dict]:
    res = (get_supabase().table("content_batches").select("*")
           .eq("id", batch_id).limit(1).execute())
    return res.data[0] if res.data else None


def get_item(item_id: str) -> Optional[dict]:
    res = (get_supabase().table("content_batch_items").select("*")
           .eq("id", item_id).limit(1).execute())
    return res.data[0] if res.data else None


def list_batches(client_id: str) -> list[dict]:
    return (get_supabase().table("content_batches").select("*")
            .eq("client_id", client_id).order("created_at", desc=True)
            .execute().data or [])


def progress_by_batch(client_id: str) -> dict[str, dict]:
    """Per-batch status counts for a client, in one paged scan (no N+1)."""
    client = get_supabase()
    agg: dict[str, dict] = {}
    page = 0
    while True:
        rows = (client.table("content_batch_items").select("batch_id, status")
                .eq("client_id", client_id)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        for r in rows:
            counts = agg.setdefault(r["batch_id"], {s: 0 for s in _STATUSES} | {"total": 0})
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            counts["total"] += 1
        if len(rows) < 1000:
            return agg
        page += 1


def list_items(batch_id: str, *, limit: int = 2000) -> list[dict]:
    client = get_supabase()
    out: list[dict] = []
    page = 0
    while len(out) < limit:
        rows = (client.table("content_batch_items").select("*")
                .eq("batch_id", batch_id).order("scheduled_at")
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.extend(rows)
        if len(rows) < 1000:
            break
        page += 1
    return out[:limit]


def due_items(now: datetime, *, limit: int = 200) -> list[dict]:
    """Scheduled items past their release time whose parent batch is still active.
    The shared scheduler calls this each tick and enqueues a job per row."""
    client = get_supabase()
    rows = (client.table("content_batch_items")
            .select("*").eq("status", "scheduled")
            .lte("scheduled_at", now.isoformat())
            .order("scheduled_at").limit(limit).execute().data or [])
    if not rows:
        return []
    batch_ids = list({r["batch_id"] for r in rows})
    active = {b["id"] for b in (client.table("content_batches").select("id, status")
              .in_("id", batch_ids).eq("status", "active").execute().data or [])}
    return [r for r in rows if r["batch_id"] in active]


def set_item_released(item_id: str, job_id: str) -> bool:
    """Flip a scheduled item to 'queued' + stamp its async_jobs id. Conditional on
    status='scheduled' so a paused/cancelled/raced row is never released twice."""
    res = (get_supabase().table("content_batch_items")
           .update({"status": "queued", "job_id": job_id})
           .eq("id", item_id).eq("status", "scheduled").execute())
    return bool(res.data)


def mark_item_running(item_id: str) -> None:
    get_supabase().table("content_batch_items").update(
        {"status": "running", "started_at": "now()"}
    ).eq("id", item_id).in_("status", ["queued", "scheduled"]).execute()


def finish_item(
    item_id: str, status: str, *, result_ref: Optional[str] = None,
    result_kind: Optional[str] = None, error: Optional[str] = None,
) -> None:
    get_supabase().table("content_batch_items").update({
        "status": status, "result_ref": result_ref, "result_kind": result_kind,
        "error": (error or None) and str(error)[:500], "completed_at": "now()",
    }).eq("id", item_id).execute()


def set_batch_status(batch_id: str, status: str) -> None:
    get_supabase().table("content_batches").update({"status": status}).eq(
        "id", batch_id).execute()


def cancel_item(item_id: str) -> bool:
    """Cancel a still-scheduled item (conditional so a released/running one is
    untouched — too late to stop)."""
    res = (get_supabase().table("content_batch_items")
           .update({"status": "cancelled"})
           .eq("id", item_id).eq("status", "scheduled").execute())
    return bool(res.data)


def reinstate_item(item_id: str) -> bool:
    """Un-cancel a scheduled item (cancelled -> scheduled), clearing prior state."""
    res = (get_supabase().table("content_batch_items")
           .update({"status": "scheduled", "job_id": None, "error": None,
                    "started_at": None, "completed_at": None})
           .eq("id", item_id).eq("status", "cancelled").execute())
    return bool(res.data)


def cancel_batch(batch_id: str) -> int:
    """Cancel a batch + all its still-pending (scheduled/queued) items. Running/
    finished items are left as historical record. Returns items cancelled."""
    client = get_supabase()
    set_batch_status(batch_id, "cancelled")
    res = (client.table("content_batch_items").update({"status": "cancelled"})
           .eq("batch_id", batch_id).in_("status", ["scheduled", "queued"]).execute())
    return len(res.data or [])


def complete_if_drained(batch_id: str) -> None:
    """Flip an active batch -> complete once no item is scheduled/queued/running.
    Leaves a paused/cancelled batch untouched."""
    client = get_supabase()
    pending = (client.table("content_batch_items").select("id")
               .eq("batch_id", batch_id)
               .in_("status", ["scheduled", "queued", "running"]).limit(1)
               .execute().data or [])
    if pending:
        return
    batch = get_batch(batch_id)
    if batch and batch["status"] == "active":
        set_batch_status(batch_id, "complete")
