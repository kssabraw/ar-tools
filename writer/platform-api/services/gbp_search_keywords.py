"""GBP search-keywords ingestion + read.

Pulls the search terms that drove impressions for a listing, per calendar month,
from the Business Profile Performance API and stores them in
``gbp_search_keyword_monthly`` (one row per location×month×keyword). Monthly
granularity; low-volume terms come back as a privacy "threshold" flagged by
``is_threshold``.

Triggered by ``job_type='gbp_search_keywords'`` jobs (scheduled monthly by
gsc_scheduler, or a backfill). Mirrors services/gbp_metrics_ingest.py; gated on
``settings.gbp_metrics_enabled``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import gbp_performance_service as gbp

logger = logging.getLogger(__name__)


@dataclass
class KeywordIngestResult:
    status: str  # 'ok' | 'failed'
    months: int
    rows: int
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested.
# ----------------------------------------------------------------------------
def month_start(d: date) -> date:
    return d.replace(day=1)


def recent_complete_months(today: date, n: int) -> list[date]:
    """The ``n`` most recent *complete* calendar months as first-of-month dates,
    most-recent first. The current month is excluded (its data is partial, and
    GBP search keywords lag anyway)."""
    out: list[date] = []
    m = month_start(today)
    for _ in range(max(1, n)):
        m = month_start(m - timedelta(days=1))
        out.append(m)
    return out


def aggregate_keywords(rows: list[dict], limit: int = 25) -> tuple[list[dict], int]:
    """Sum a single month's keyword rows across locations → ``([{keyword, value,
    is_threshold}], total)`` sorted by value desc. ``is_threshold`` is set when
    *every* contribution to that keyword was a privacy-floored threshold. Pure."""
    agg: dict[str, dict] = {}
    for r in rows:
        kw = r.get("keyword")
        if not kw:
            continue
        cell = agg.setdefault(kw, {"keyword": kw, "value": 0, "exact": False})
        cell["value"] += int(r.get("value", 0) or 0)
        if not r.get("is_threshold"):
            cell["exact"] = True
    items = [
        {"keyword": c["keyword"], "value": c["value"], "is_threshold": not c["exact"]}
        for c in agg.values()
    ]
    items.sort(key=lambda x: x["value"], reverse=True)
    total = sum(i["value"] for i in items)
    return items[:limit], total


# ----------------------------------------------------------------------------
# Ingestion
# ----------------------------------------------------------------------------
def ingest_location_keywords(location_row_id: str, months_back: int = 2) -> KeywordIngestResult:
    """Pull the last ``months_back`` complete months of search keywords for one
    location and replace that month's stored rows (idempotent per month, so a
    keyword dropping out of the list is reflected)."""
    if not settings.gbp_metrics_enabled:
        return KeywordIngestResult(status="failed", months=0, rows=0, error="gbp_metrics_disabled")

    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations").select("id, location_id, access_status")
        .eq("id", location_row_id).limit(1).execute()
    ).data or []
    if not found:
        return KeywordIngestResult(status="failed", months=0, rows=0, error="location_not_found")
    loc = found[0]

    try:
        location_id = gbp.normalize_location_id(loc["location_id"])
    except ValueError as exc:
        return KeywordIngestResult(status="failed", months=0, rows=0, error=str(exc))

    total_rows = 0
    months = recent_complete_months(date.today(), months_back)
    last_error: Optional[str] = None
    for month in months:
        try:
            records = gbp.fetch_search_keywords(location_id, month)
        except Exception as exc:  # noqa: BLE001 — one month failing must not abort the rest
            from services import gsc_service

            code = gsc_service._extract_status_code(exc)
            last_error = f"{gbp.classify_access_error(code).detail or 'fetch_failed'} (http_{code})"
            logger.warning("gbp_keywords_fetch_failed",
                           extra={"location_row_id": location_row_id, "month": month.isoformat(), "error": last_error})
            continue
        rows = [
            {
                "location_row_id": location_row_id, "month": month.isoformat(),
                "keyword": r["keyword"], "value": int(r.get("value", 0) or 0),
                "is_threshold": bool(r.get("is_threshold")), "updated_at": "now()",
            }
            for r in records if r.get("keyword")
        ]
        try:
            (supabase.table("gbp_search_keyword_monthly").delete()
             .eq("location_row_id", location_row_id).eq("month", month.isoformat()).execute())
            if rows:
                supabase.table("gbp_search_keyword_monthly").insert(rows).execute()
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            logger.error("gbp_keywords_upsert_failed",
                         extra={"location_row_id": location_row_id, "month": month.isoformat(), "error": last_error})
            continue
        total_rows += len(rows)

    status = "ok" if total_rows or last_error is None else "failed"
    return KeywordIngestResult(status=status, months=len(months), rows=total_rows, error=last_error if status == "failed" else None)


async def run_gbp_search_keywords_job(job: dict) -> None:
    """async_jobs handler for job_type='gbp_search_keywords'."""
    payload = job.get("payload") or {}
    location_row_id = payload.get("location_row_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not location_row_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing location_row_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    result = ingest_location_keywords(location_row_id, int(payload.get("months_back", 2)))
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"months": result.months, "rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()


# ----------------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------------
def read_keywords(client_id: str, month: Optional[str] = None, limit: int = 25) -> dict:
    """Top search keywords for a client's verified locations. Defaults to the
    latest month with data; ``month`` (YYYY-MM-01) picks a specific one. Returns
    ``{month, months:[…available], keywords:[…], total}``."""
    supabase = get_supabase()
    locs = (
        supabase.table("gbp_locations").select("id")
        .eq("client_id", client_id).eq("access_status", "ok").execute()
    ).data or []
    loc_ids = [row["id"] for row in locs]
    if not loc_ids:
        return {"month": None, "months": [], "keywords": [], "total": 0}

    # Distinct months present. Paginated on the full PK (month, location_row_id,
    # keyword) past PostgREST's ~1000-row default cap — an unpaged read would drop
    # the oldest rows, silently losing older months from the picker once a few
    # months of history exist (a 12-month backfill across N locations far exceeds
    # the cap). A total order keeps offset pages from splitting/dropping rows.
    available_set: set[str] = set()
    page, offset = 1000, 0
    while True:
        batch = (
            supabase.table("gbp_search_keyword_monthly").select("month")
            .in_("location_row_id", loc_ids)
            .order("month", desc=True).order("location_row_id").order("keyword")
            .range(offset, offset + page - 1).execute()
        ).data or []
        available_set.update(r["month"] for r in batch)
        if len(batch) < page:
            break
        offset += page
    available = sorted(available_set, reverse=True)
    if not available:
        return {"month": None, "months": [], "keywords": [], "total": 0}
    target = month if (month and month in available) else available[0]

    # Paginated too (a multi-location client can exceed the ~1000-row cap in a
    # single month), so the cross-location aggregate can't silently undercount.
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (
            supabase.table("gbp_search_keyword_monthly").select("keyword, value, is_threshold, location_row_id")
            .in_("location_row_id", loc_ids).eq("month", target)
            .order("location_row_id").order("keyword")
            .range(offset, offset + page - 1).execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    keywords, total = aggregate_keywords(rows, limit)
    return {"month": target, "months": available, "keywords": keywords, "total": total}
