"""GBP reviews — v4 ingest/read layer for the GBP Insights dashboard.

Distinct from ``services.gbp_reviews`` (the Outscraper feed powering the client
PDF report): this uses the first-party Google My Business **v4** reviews API
(``services.gbp_reviews_api``) — free + complete. Mirrors
``services.gbp_search_keywords``: the pure API client is separate; this module
holds the async-job handler, the pure period-windowing helpers, and (Phase 2)
storage + the dashboard read.

This first slice runs the ``gbp_reviews`` job in **verify mode**: it fetches a
location's reviews and writes a summary (counts, average, a recent-window slice
proving the ``createTime`` dates are usable) to the job result — no storage yet.
Storage + the dashboard "Reviews this period" panel land once v4 access is
confirmed reachable for this project (the v4 API can need allowlisting).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase
from fastapi import HTTPException

from services import gbp_reviews_api

logger = logging.getLogger(__name__)


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
# Job handler (verify mode)
# ----------------------------------------------------------------------------
def _finish(supabase, job_id: str, status: str, result: Optional[dict] = None,
            error: Optional[str] = None) -> None:
    supabase.table("async_jobs").update(
        {"status": status, "result": result, "error": error, "completed_at": "now()"}
    ).eq("id", job_id).execute()


async def run_gbp_reviews_job(job: dict) -> None:
    """async_jobs handler for job_type='gbp_reviews' (verify mode).

    Fetches one location's reviews and writes a summary to the job result:
    ``{fetched, total_count, average_rating, truncated, newest, oldest,
    last_30d_count, last_30d_avg, sample}``. A blocked/failed v4 call records the
    classified reason as the job error rather than raising."""
    payload = job.get("payload") or {}
    location_row_id = payload.get("location_row_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not location_row_id:
        _finish(supabase, job_id, "failed", error="missing location_row_id")
        return

    found = (
        supabase.table("gbp_locations")
        .select("id, account_id, location_id, title")
        .eq("id", location_row_id).limit(1).execute()
    ).data or []
    if not found:
        _finish(supabase, job_id, "failed", error="location_not_found")
        return
    loc = found[0]
    if not loc.get("account_id"):
        _finish(supabase, job_id, "failed", error="location_has_no_account_id")
        return

    try:
        data = gbp_reviews_api.list_reviews(loc["account_id"], loc["location_id"])
    except HTTPException as exc:
        _finish(supabase, job_id, "failed", error=str(exc.detail))
        return
    except Exception as exc:  # noqa: BLE001 — record the reason, don't wedge the job
        logger.warning("gbp_reviews_job_failed", extra={"job_id": job_id, "error": str(exc)})
        _finish(supabase, job_id, "failed", error=str(exc)[:300])
        return

    reviews = data["reviews"]
    times = sorted(r.get("create_time", "") for r in reviews if r.get("create_time"))
    today = date.today()
    last_30d = summarize_period(reviews, (today - timedelta(days=30)).isoformat(), today.isoformat())
    summary = {
        "location": loc.get("title"),
        "fetched": len(reviews),
        "total_count": data["total_count"],
        "average_rating": data["average_rating"],
        "truncated": data["truncated"],
        "newest": times[-1] if times else None,
        "oldest": times[0] if times else None,
        "last_30d_count": last_30d["count"],
        "last_30d_avg": last_30d["average_rating"],
        "sample": [
            {"reviewer": r["reviewer"], "rating": r["rating"],
             "create_time": r["create_time"], "has_reply": r["has_reply"],
             "text": (r["text"] or "")[:160]}
            for r in reviews[:3]
        ],
    }
    _finish(supabase, job_id, "complete", result=summary)
