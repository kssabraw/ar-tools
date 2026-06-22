"""GSC daily query×date ingestion.

Organic Rank Tracker (Module #4), M2 "Sync + storage". Pulls a window of GSC
Search Analytics rows for a property and idempotently upserts them into
``gsc_query_daily``, recording every run in ``sync_runs``. A 403 (service
account removed from the property) flips the property to ``no_access`` so the
UI can surface "reconnect needed".

Triggered by ``job_type='gsc_ingest'`` jobs (enqueued by gsc_scheduler) or the
manual ingest endpoint. See docs/modules/organic-rank-tracker-prd-v1_0.md §6.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import gsc_service

logger = logging.getLogger(__name__)

# gsc_query_daily is query×date — NO page dimension. keys[0]=query, keys[1]=date.
_DIMENSIONS = ["query", "date"]
_JOB_TYPE = "gsc_query_daily"

# gsc_query_page_daily is query×page×date. keys[0]=query, keys[1]=page, keys[2]=date.
_PAGE_DIMENSIONS = ["query", "page", "date"]
_PAGE_JOB_TYPE = "gsc_query_page_daily"


@dataclass
class IngestResult:
    status: str  # 'ok' | 'failed'
    rows: int
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def compute_window(today: date, repull_days: int) -> tuple[str, str]:
    """Inclusive [start, end] window ending today, `repull_days` days long.

    GSC backfills the most recent ~2–3 days late, so each run re-pulls a short
    trailing window; idempotent upserts make the overlap harmless and a missed
    run self-heals on the next pull.
    """
    days = max(1, repull_days)
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


def parse_query_daily_rows(property_id: str, rows: list[dict]) -> list[dict]:
    """Map raw GSC rows (dimensions = query, date) to gsc_query_daily records."""
    parsed: list[dict] = []
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        parsed.append(
            {
                "property_id": property_id,
                "query": keys[0],
                "date": keys[1],
                "clicks": int(row.get("clicks", 0) or 0),
                "impressions": int(row.get("impressions", 0) or 0),
                "ctr": float(row.get("ctr", 0) or 0),
                "position": row.get("position"),
            }
        )
    return parsed


def parse_query_page_rows(property_id: str, rows: list[dict]) -> list[dict]:
    """Map raw GSC rows (dimensions = query, page, date) to gsc_query_page_daily."""
    parsed: list[dict] = []
    for row in rows:
        keys = row.get("keys") or []
        if len(keys) < 3:
            continue
        parsed.append(
            {
                "property_id": property_id,
                "query": keys[0],
                "page": keys[1],
                "date": keys[2],
                "clicks": int(row.get("clicks", 0) or 0),
                "impressions": int(row.get("impressions", 0) or 0),
                "ctr": float(row.get("ctr", 0) or 0),
                "position": row.get("position"),
            }
        )
    return parsed


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _record_sync_run(
    property_id: str, status: str, rows: int, start: str, end: str, error: Optional[str]
) -> None:
    try:
        get_supabase().table("sync_runs").insert(
            {
                "property_id": property_id,
                "job_type": _JOB_TYPE,
                "start_date": start,
                "end_date": end,
                "rows": rows,
                "status": status,
                "error": error[:1000] if error else None,
            }
        ).execute()
    except Exception as exc:  # pragma: no cover - observability must not crash ingest
        logger.error("sync_run_record_failed", extra={"error": str(exc)})


def ingest_property(
    property_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> IngestResult:
    """Pull a window for one property and upsert into gsc_query_daily.

    Window defaults to the trailing `gsc_repull_days`. Records a sync_runs row
    and, on a 403, marks the property no_access. Returns an IngestResult rather
    than raising for handled errors so the job worker can report status.
    """
    supabase = get_supabase()
    found = (
        supabase.table("gsc_properties").select("*").eq("id", property_id).limit(1).execute()
    )
    if not found.data:
        return IngestResult(status="failed", rows=0, error="property_not_found")
    prop = found.data[0]

    if start_date is None or end_date is None:
        start_date, end_date = compute_window(date.today(), settings.gsc_repull_days)

    try:
        site_url = gsc_service.normalize_site_url(prop["site_url"], prop["property_type"])
        raw = gsc_service.fetch_search_analytics(site_url, _DIMENSIONS, start_date, end_date)
    except ValueError as exc:
        _record_sync_run(property_id, "failed", 0, start_date, end_date, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))
    except Exception as exc:
        code = gsc_service._extract_status_code(exc)
        verdict = gsc_service.classify_access_error(code)
        if verdict.status == "no_access":
            supabase.table("gsc_properties").update(
                {"access_status": "no_access", "updated_at": "now()"}
            ).eq("id", property_id).execute()
        err = f"{verdict.detail or 'fetch_failed'} (http_{code})" if code else "fetch_failed"
        logger.warning("gsc_ingest_fetch_failed", extra={"property_id": property_id, "error": err})
        _record_sync_run(property_id, "failed", 0, start_date, end_date, err)
        return IngestResult(status="failed", rows=0, error=err)

    records = parse_query_daily_rows(property_id, raw)
    try:
        if records:
            supabase.table("gsc_query_daily").upsert(
                records, on_conflict="property_id,date,query"
            ).execute()
    except Exception as exc:
        logger.error("gsc_ingest_upsert_failed", extra={"property_id": property_id, "error": str(exc)})
        _record_sync_run(property_id, "failed", 0, start_date, end_date, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))

    _record_sync_run(property_id, "ok", len(records), start_date, end_date, None)
    logger.info(
        "gsc_ingest_complete",
        extra={"property_id": property_id, "rows": len(records), "start": start_date, "end": end_date},
    )
    return IngestResult(status="ok", rows=len(records))


def ingest_property_pages(property_id: str) -> IngestResult:
    """Pull the query×page×date window for a property → gsc_query_page_daily.

    Weekly cadence: the page dimension multiplies rows, so we pull a trailing
    `gsc_page_window_days` window rather than daily.
    """
    supabase = get_supabase()
    found = supabase.table("gsc_properties").select("*").eq("id", property_id).limit(1).execute()
    if not found.data:
        return IngestResult(status="failed", rows=0, error="property_not_found")
    prop = found.data[0]

    end = date.today()
    start = end - timedelta(days=settings.gsc_page_window_days)
    start_date, end_date = start.isoformat(), end.isoformat()

    try:
        site_url = gsc_service.normalize_site_url(prop["site_url"], prop["property_type"])
        raw = gsc_service.fetch_search_analytics(site_url, _PAGE_DIMENSIONS, start_date, end_date)
    except Exception as exc:
        code = gsc_service._extract_status_code(exc)
        err = f"{gsc_service.classify_access_error(code).detail or 'fetch_failed'}" if code else "fetch_failed"
        get_supabase().table("sync_runs").insert(
            {"property_id": property_id, "job_type": _PAGE_JOB_TYPE, "start_date": start_date,
             "end_date": end_date, "rows": 0, "status": "failed", "error": err}
        ).execute()
        return IngestResult(status="failed", rows=0, error=err)

    records = parse_query_page_rows(property_id, raw)
    if records:
        supabase.table("gsc_query_page_daily").upsert(
            records, on_conflict="property_id,date,query,page"
        ).execute()
    supabase.table("sync_runs").insert(
        {"property_id": property_id, "job_type": _PAGE_JOB_TYPE, "start_date": start_date,
         "end_date": end_date, "rows": len(records), "status": "ok", "error": None}
    ).execute()
    return IngestResult(status="ok", rows=len(records))


async def run_gsc_ingest_job(job: dict) -> None:
    """async_jobs handler for job_type='gsc_ingest'."""
    payload = job.get("payload") or {}
    property_id = payload.get("property_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not property_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing property_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = ingest_property(property_id, payload.get("start_date"), payload.get("end_date"))
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()

    # Chain the date-axis materialize + status recompute after fresh data lands.
    # Keywords are client-anchored, so materialize the property's client.
    if result.status == "ok":
        from services.rank_materialize import enqueue_materialize

        prop = (
            supabase.table("gsc_properties").select("client_id").eq("id", property_id).limit(1).execute()
        )
        if prop.data:
            enqueue_materialize(prop.data[0]["client_id"])


async def run_gsc_page_ingest_job(job: dict) -> None:
    """async_jobs handler for job_type='gsc_page_ingest' (weekly query×page)."""
    from services.rank_materialize import enqueue_materialize

    payload = job.get("payload") or {}
    property_id = payload.get("property_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not property_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing property_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = ingest_property_pages(property_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()

    # Resolve canonical URLs from the fresh page data.
    if result.status == "ok":
        prop = supabase.table("gsc_properties").select("client_id").eq("id", property_id).limit(1).execute()
        if prop.data:
            enqueue_materialize(prop.data[0]["client_id"])
