"""GA4 daily metric ingestion.

Client Reporting Phase 2. Pulls a trailing window of per-day GA4 metrics for a
property and idempotently upserts them into ``ga4_daily``, recording every run
in ``ga4_sync_runs``. A 401/403 (service account removed as a Viewer) flips the
property to ``no_access`` so the UI can surface "reconnect needed".

Triggered by ``job_type='ga4_ingest'`` jobs (enqueued by gsc_scheduler's daily
pass, gated on ``ga4_ingest_enabled``) or the manual ingest endpoint. Mirrors
services/gsc_ingest.py.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import ga4_service

logger = logging.getLogger(__name__)


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

    GA4 settles the most recent ~1–2 days late, so each run re-pulls a short
    trailing window; idempotent upserts make the overlap harmless and a missed
    run self-heals on the next pull."""
    days = max(1, repull_days)
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


def to_records(property_row_id: str, daily: list[dict]) -> list[dict]:
    """Map fetch_daily_metrics() output to ga4_daily upsert records."""
    records: list[dict] = []
    for row in daily:
        if not row.get("date"):
            continue
        records.append(
            {
                "property_id": property_row_id,
                "date": row["date"],
                "sessions": int(row.get("sessions", 0) or 0),
                "total_users": int(row.get("total_users", 0) or 0),
                "screen_page_views": int(row.get("screen_page_views", 0) or 0),
                "conversions": row.get("conversions"),
                "channels": row.get("channels") or {},
            }
        )
    return records


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _record_sync_run(
    property_row_id: str, status: str, rows: int, start: str, end: str, error: Optional[str]
) -> None:
    try:
        get_supabase().table("ga4_sync_runs").insert(
            {
                "property_id": property_row_id,
                "job_type": "ga4_ingest",
                "start_date": start,
                "end_date": end,
                "rows": rows,
                "status": status,
                "error": error[:1000] if error else None,
            }
        ).execute()
    except Exception as exc:  # pragma: no cover - observability must not crash ingest
        logger.error("ga4_sync_run_record_failed", extra={"error": str(exc)})


def ingest_property(
    property_row_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> IngestResult:
    """Pull a window for one property and upsert into ga4_daily.

    ``property_row_id`` is the ga4_properties PK (not the GA4 numeric id). Window
    defaults to the trailing ``ga4_repull_days``. Records a ga4_sync_runs row
    and, on a 401/403, marks the property no_access. Returns an IngestResult
    rather than raising for handled errors so the job worker can report status."""
    supabase = get_supabase()
    found = (
        supabase.table("ga4_properties").select("*").eq("id", property_row_id).limit(1).execute()
    )
    if not found.data:
        return IngestResult(status="failed", rows=0, error="property_not_found")
    prop = found.data[0]

    if start_date is None or end_date is None:
        start_date, end_date = compute_window(date.today(), settings.ga4_repull_days)

    try:
        normalized = ga4_service.normalize_property_id(prop["property_id"])
        daily = ga4_service.fetch_daily_metrics(normalized, start_date, end_date)
    except ValueError as exc:
        _record_sync_run(property_row_id, "failed", 0, start_date, end_date, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))
    except ga4_service.Ga4ApiError as exc:
        verdict = ga4_service.classify_access_error(exc.status_code, exc.message)
        if verdict.status == "no_access":
            supabase.table("ga4_properties").update(
                {"access_status": "no_access", "updated_at": "now()"}
            ).eq("id", property_row_id).execute()
        err = f"{verdict.detail or 'fetch_failed'} (http_{exc.status_code})"
        logger.warning("ga4_ingest_fetch_failed", extra={"property_id": property_row_id, "error": err})
        _record_sync_run(property_row_id, "failed", 0, start_date, end_date, err)
        return IngestResult(status="failed", rows=0, error=err)
    except Exception as exc:
        logger.error("ga4_ingest_unexpected", extra={"property_id": property_row_id, "error": str(exc)})
        _record_sync_run(property_row_id, "failed", 0, start_date, end_date, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))

    records = to_records(property_row_id, daily)
    try:
        if records:
            supabase.table("ga4_daily").upsert(
                records, on_conflict="property_id,date"
            ).execute()
    except Exception as exc:
        logger.error("ga4_ingest_upsert_failed", extra={"property_id": property_row_id, "error": str(exc)})
        _record_sync_run(property_row_id, "failed", 0, start_date, end_date, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))

    _record_sync_run(property_row_id, "ok", len(records), start_date, end_date, None)
    logger.info(
        "ga4_ingest_complete",
        extra={"property_id": property_row_id, "rows": len(records), "start": start_date, "end": end_date},
    )
    return IngestResult(status="ok", rows=len(records))


def enqueue_ingest(property_row_id: str) -> str:
    """Enqueue a default-window GA4 ingest job (deduped against pending/running).

    Returns the existing job id when an ingest is already queued/running for this
    property (so a manual "Sync now" rides the in-flight pull) else the new one."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "ga4_ingest")
        .eq("entity_id", property_row_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = supabase.table("async_jobs").insert(
        {"job_type": "ga4_ingest", "entity_id": property_row_id, "payload": {"property_id": property_row_id}}
    ).execute()
    return inserted.data[0]["id"]


async def run_ga4_ingest_job(job: dict) -> None:
    """async_jobs handler for job_type='ga4_ingest'."""
    payload = job.get("payload") or {}
    property_row_id = payload.get("property_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not property_row_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing property_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    # ingest_property does blocking GA4 HTTP + DB I/O; keep it off the worker's
    # event loop so a slow Google call can't stall the scheduler / other jobs.
    result = await asyncio.to_thread(
        ingest_property, property_row_id, payload.get("start_date"), payload.get("end_date")
    )
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
