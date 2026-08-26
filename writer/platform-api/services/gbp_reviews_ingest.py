"""GBP reviews — v4 ingest/read layer for the GBP Insights dashboard.

Distinct from ``services.gbp_reviews`` (the Outscraper feed powering the client
PDF report): this uses the first-party Google My Business **v4** reviews API
(``services.gbp_reviews_api``) — free + complete. Mirrors
``services.gbp_search_keywords``: the pure API client is separate; this module
holds the async-job handler, the pure period-windowing helpers, storage
(``gbp_location_reviews``), and the dashboard "reviews this period" read.

The ``gbp_reviews`` job fetches a location's reviews and replaces the stored set
(delete-then-insert, so Google-side deletions are reflected), writing a summary
to the job result. ``read_period_reviews`` windows the stored reviews to the
dashboard's date range for the panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase
from fastapi import HTTPException

from services import gbp_reviews_api

logger = logging.getLogger(__name__)


@dataclass
class ReviewIngestResult:
    """Small ingest result: status ('ok'|'failed') + a summary dict or an error."""

    status: str
    summary: Optional[dict] = None
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure period-windowing helpers (no I/O) — the crux of "reviews posted during
# the reporting period", operating on the v4 shape (ISO ``create_time``).
# ----------------------------------------------------------------------------
def review_date(create_time: str) -> Optional[str]:
    """The ``YYYY-MM-DD`` calendar date (UTC) of a v4 ISO-8601 ``createTime``.

    v4 ``createTime`` is UTC (``…Z``); the leading 10 chars are the date. Returns
    None for anything too short/malformed to carry a date. Pure."""
    if not isinstance(create_time, str) or len(create_time) < 10:
        return None
    d = create_time[:10]
    return d if d[4] == "-" and d[7] == "-" else None


def in_period(create_time: str, start: str, end: str) -> bool:
    """Whether a review's create date falls within ``[start, end]`` (inclusive,
    ``YYYY-MM-DD`` strings — ISO dates sort lexically). Pure."""
    d = review_date(create_time)
    return bool(d and start <= d <= end)


def summarize_period(reviews: list[dict], start: str, end: str) -> dict:
    """Reviews created within ``[start, end]`` → ``{count, average_rating, items}``
    (items newest-first). ``average_rating`` is over the period's *rated* reviews
    (None when none). Pure — the exact shape the dashboard panel will render."""
    picked = [r for r in reviews if in_period(r.get("create_time", ""), start, end)]
    picked.sort(key=lambda r: r.get("create_time", ""), reverse=True)
    rated = [r["rating"] for r in picked if isinstance(r.get("rating"), (int, float))]
    avg = round(sum(rated) / len(rated), 2) if rated else None
    return {"count": len(picked), "average_rating": avg, "items": picked}


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------
def _review_rows(location_row_id: str, reviews: list[dict]) -> list[dict]:
    """Map parsed v4 reviews to gbp_location_reviews rows (drop id-less). Pure."""
    rows: list[dict] = []
    for r in reviews:
        rid = r.get("review_id")
        if not rid:
            continue
        rows.append({
            "location_row_id": location_row_id,
            "review_id": rid,
            "reviewer": r.get("reviewer") or "",
            "rating": r.get("rating"),
            "text": r.get("text") or "",
            "create_time": r.get("create_time") or None,
            "update_time": r.get("update_time") or None,
            "has_reply": bool(r.get("has_reply")),
            "updated_at": "now()",
        })
    return rows


def store_reviews(supabase, location_row_id: str, reviews: list[dict]) -> int:
    """Replace a location's stored reviews with ``reviews`` (delete-then-insert, so
    Google-side deletions drop out). Returns the row count written."""
    rows = _review_rows(location_row_id, reviews)
    supabase.table("gbp_location_reviews").delete().eq("location_row_id", location_row_id).execute()
    for i in range(0, len(rows), 500):  # chunk large sets
        supabase.table("gbp_location_reviews").insert(rows[i:i + 500]).execute()
    return len(rows)


def ingest_location_reviews(location_row_id: str) -> ReviewIngestResult:
    """Fetch one location's reviews from v4 and replace the stored set.

    Returns a small result carrying the counts/summary or the classified error.
    Best-effort at the API boundary — the caller records the reason."""
    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations")
        .select("id, account_id, location_id, title")
        .eq("id", location_row_id).limit(1).execute()
    ).data or []
    if not found:
        return ReviewIngestResult(status="failed", error="location_not_found")
    loc = found[0]
    if not loc.get("account_id"):
        return ReviewIngestResult(status="failed", error="location_has_no_account_id")

    try:
        data = gbp_reviews_api.list_reviews(loc["account_id"], loc["location_id"])
    except HTTPException as exc:
        return ReviewIngestResult(status="failed", error=str(exc.detail))
    except Exception as exc:  # noqa: BLE001 — record the reason, don't raise
        logger.warning("gbp_reviews_ingest_failed",
                       extra={"location_row_id": location_row_id, "error": str(exc)})
        return ReviewIngestResult(status="failed", error=str(exc)[:300])

    reviews = data["reviews"]
    stored = store_reviews(supabase, location_row_id, reviews)
    today = date.today()
    last_30d = summarize_period(reviews, (today - timedelta(days=30)).isoformat(), today.isoformat())
    return ReviewIngestResult(status="ok", summary={
        "location": loc.get("title"),
        "stored": stored,
        "total_count": data["total_count"],
        "average_rating": data["average_rating"],
        "truncated": data["truncated"],
        "last_30d_count": last_30d["count"],
        "last_30d_avg": last_30d["average_rating"],
    })


# ----------------------------------------------------------------------------
# Job handler
# ----------------------------------------------------------------------------
def _finish(supabase, job_id: str, status: str, result: Optional[dict] = None,
            error: Optional[str] = None) -> None:
    supabase.table("async_jobs").update(
        {"status": status, "result": result, "error": error, "completed_at": "now()"}
    ).eq("id", job_id).execute()


async def run_gbp_reviews_job(job: dict) -> None:
    """async_jobs handler for job_type='gbp_reviews': fetch one location's reviews
    from v4 and replace the stored set. Records the summary or the classified
    reason on the job."""
    payload = job.get("payload") or {}
    location_row_id = payload.get("location_row_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not location_row_id:
        _finish(supabase, job_id, "failed", error="missing location_row_id")
        return
    try:
        result = ingest_location_reviews(location_row_id)
    except Exception as exc:  # noqa: BLE001 — never wedge the job on a store error
        logger.error("gbp_reviews_job_error", extra={"job_id": job_id, "error": str(exc)})
        _finish(supabase, job_id, "failed", error=str(exc)[:300])
        return
    _finish(
        supabase, job_id,
        "complete" if result.status == "ok" else "failed",
        result=result.summary, error=result.error,
    )


# ----------------------------------------------------------------------------
# Dashboard read — reviews posted within [start, end]
# ----------------------------------------------------------------------------
def read_period_reviews(client_id: str, start: str, end: str, limit: int = 50) -> dict:
    """Reviews across a client's verified locations posted within ``[start, end]``
    (YYYY-MM-DD, inclusive). Returns ``{count, average_rating, items, overall_rating,
    overall_count}`` — the period slice plus the current all-time rating/count for
    context. Newest-first, capped at ``limit`` items."""
    supabase = get_supabase()
    locs = (
        supabase.table("gbp_locations").select("id")
        .eq("client_id", client_id).eq("access_status", "ok").execute()
    ).data or []
    loc_ids = [row["id"] for row in locs]
    empty = {"count": 0, "average_rating": None, "items": [], "overall_rating": None, "overall_count": 0}
    if not loc_ids:
        return empty

    # create_time is a timestamptz; [start, end] are calendar dates → include the
    # whole end day by bounding with the exclusive next-day midnight.
    end_excl = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    rows: list[dict] = []
    page, offset = 1000, 0
    while True:
        batch = (
            supabase.table("gbp_location_reviews")
            .select("review_id, reviewer, rating, text, create_time, has_reply, location_row_id")
            .in_("location_row_id", loc_ids)
            .gte("create_time", start).lt("create_time", end_excl)
            .order("create_time", desc=True).order("location_row_id").order("review_id")
            .range(offset, offset + page - 1).execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page

    rated = [r["rating"] for r in rows if isinstance(r.get("rating"), (int, float))]
    avg = round(sum(rated) / len(rated), 2) if rated else None
    items = [
        {"reviewer": r.get("reviewer") or "", "rating": r.get("rating"),
         "text": r.get("text") or "", "date": (r.get("create_time") or "")[:10],
         "has_reply": bool(r.get("has_reply"))}
        for r in rows[:limit]
    ]
    # Overall rating/count = the client's captured GBP snapshot (all-time context).
    overall_rating = overall_count = None
    try:
        crow = (
            supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute()
        ).data or []
        gbp = (crow[0].get("gbp") if crow else None) or {}
        overall_rating = gbp.get("gbp_rating")
        overall_count = gbp.get("gbp_review_count")
    except Exception:  # noqa: BLE001 — context only
        pass
    return {
        "count": len(rows), "average_rating": avg, "items": items,
        "overall_rating": overall_rating, "overall_count": overall_count or 0,
    }
