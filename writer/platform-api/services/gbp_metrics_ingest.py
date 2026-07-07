"""GBP daily performance-metrics ingestion.

Pulls a window of Business Profile Performance metrics for a registered location
and idempotently upserts them into ``gbp_metric_daily`` (long/narrow: one row
per location×date×metric), recording each run in ``gbp_sync_runs``. A 403
(service account no longer a Manager on the profile) flips the location to
``no_access`` so the UI can surface "reconnect needed".

Triggered by ``job_type='gbp_metrics_ingest'`` jobs (enqueued by gsc_scheduler)
or the manual ingest endpoint. Mirrors services/gsc_ingest.py.

Dormant until ``settings.gbp_metrics_enabled`` and Google access land.
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
class IngestResult:
    status: str  # 'ok' | 'failed'
    rows: int
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def compute_window(today: date, repull_days: int) -> tuple[date, date]:
    """Inclusive [start, end] window ending today, `repull_days` days long.

    GBP performance data arrives ~3–5 days late, so each run re-pulls a trailing
    window; idempotent upserts make the overlap harmless and a missed run
    self-heals on the next pull.
    """
    days = max(1, repull_days)
    start = today - timedelta(days=days - 1)
    return start, today


def parse_metric_rows(location_row_id: str, records: list[dict]) -> list[dict]:
    """Map parsed Performance records to gbp_metric_daily upsert records."""
    rows: list[dict] = []
    for r in records:
        metric, d = r.get("metric"), r.get("date")
        if not metric or not d:
            continue
        rows.append(
            {
                "location_row_id": location_row_id,
                "date": d,
                "metric": metric,
                "value": int(r.get("value", 0) or 0),
                "updated_at": "now()",
            }
        )
    return rows


def compute_metric_growth(
    daily_rows: list[dict], end: date, window_days: int, metrics: Optional[list[str]] = None
) -> dict[str, dict]:
    """Sum each metric over the trailing `window_days` vs the prior equal window.

    ``daily_rows`` are ``gbp_metric_daily`` rows ({date, metric, value}). Returns
    ``{metric: {current, previous, delta, pct}}``; ``pct`` is None when the prior
    window is zero (avoid divide-by-zero / infinite growth). Pure — the report
    consumer + tests use it without touching the DB.
    """
    cur_start = end - timedelta(days=window_days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window_days - 1)

    cur: dict[str, int] = {}
    prev: dict[str, int] = {}
    for row in daily_rows:
        m = row.get("metric")
        if metrics and m not in metrics:
            continue
        d = row.get("date")
        try:
            dd = date.fromisoformat(d) if isinstance(d, str) else d
        except (TypeError, ValueError):
            continue
        val = int(row.get("value", 0) or 0)
        if cur_start <= dd <= end:
            cur[m] = cur.get(m, 0) + val
        elif prev_start <= dd <= prev_end:
            prev[m] = prev.get(m, 0) + val

    out: dict[str, dict] = {}
    for m in set(cur) | set(prev):
        c, p = cur.get(m, 0), prev.get(m, 0)
        pct = round((c - p) / p * 100, 1) if p else None
        out[m] = {"current": c, "previous": p, "delta": c - p, "pct": pct}
    return out


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _record_sync_run(
    location_row_id: str, status: str, rows: int, start: str, end: str, error: Optional[str]
) -> None:
    try:
        get_supabase().table("gbp_sync_runs").insert(
            {
                "location_row_id": location_row_id,
                "start_date": start,
                "end_date": end,
                "rows": rows,
                "status": status,
                "error": error[:1000] if error else None,
            }
        ).execute()
    except Exception as exc:  # pragma: no cover - observability must not crash ingest
        logger.error("gbp_sync_run_record_failed", extra={"error": str(exc)})


def ingest_location(
    location_row_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> IngestResult:
    """Pull a window for one location and upsert into gbp_metric_daily.

    Window defaults to the trailing `gbp_metrics_repull_days`. Records a
    gbp_sync_runs row and, on a 403, marks the location no_access. Returns an
    IngestResult rather than raising for handled errors.
    """
    if not settings.gbp_metrics_enabled:
        return IngestResult(status="failed", rows=0, error="gbp_metrics_disabled")

    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations").select("*").eq("id", location_row_id).limit(1).execute()
    )
    if not found.data:
        return IngestResult(status="failed", rows=0, error="location_not_found")
    loc = found.data[0]

    if start_date and end_date:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    else:
        start, end = compute_window(date.today(), settings.gbp_metrics_repull_days)
    start_s, end_s = start.isoformat(), end.isoformat()

    try:
        location_id = gbp.normalize_location_id(loc["location_id"])
        records = gbp.fetch_daily_metrics(location_id, start, end)
    except ValueError as exc:
        _record_sync_run(location_row_id, "failed", 0, start_s, end_s, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))
    except Exception as exc:
        from services import gsc_service

        code = gsc_service._extract_status_code(exc)
        verdict = gbp.classify_access_error(code)
        if verdict.status == "no_access":
            supabase.table("gbp_locations").update(
                {"access_status": "no_access", "updated_at": "now()"}
            ).eq("id", location_row_id).execute()
        err = f"{verdict.detail or 'fetch_failed'} (http_{code})" if code else "fetch_failed"
        logger.warning("gbp_ingest_fetch_failed", extra={"location_row_id": location_row_id, "error": err})
        _record_sync_run(location_row_id, "failed", 0, start_s, end_s, err)
        return IngestResult(status="failed", rows=0, error=err)

    rows = parse_metric_rows(location_row_id, records)
    try:
        if rows:
            supabase.table("gbp_metric_daily").upsert(
                rows, on_conflict="location_row_id,date,metric"
            ).execute()
        supabase.table("gbp_locations").update(
            {"last_synced_at": "now()", "updated_at": "now()"}
        ).eq("id", location_row_id).execute()
    except Exception as exc:
        logger.error("gbp_ingest_upsert_failed", extra={"location_row_id": location_row_id, "error": str(exc)})
        _record_sync_run(location_row_id, "failed", 0, start_s, end_s, str(exc))
        return IngestResult(status="failed", rows=0, error=str(exc))

    _record_sync_run(location_row_id, "ok", len(rows), start_s, end_s, None)
    logger.info(
        "gbp_ingest_complete",
        extra={"location_row_id": location_row_id, "rows": len(rows), "start": start_s, "end": end_s},
    )
    return IngestResult(status="ok", rows=len(rows))


async def run_gbp_metrics_ingest_job(job: dict) -> None:
    """async_jobs handler for job_type='gbp_metrics_ingest'."""
    payload = job.get("payload") or {}
    location_row_id = payload.get("location_row_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not location_row_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing location_row_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = ingest_location(location_row_id, payload.get("start_date"), payload.get("end_date"))
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
