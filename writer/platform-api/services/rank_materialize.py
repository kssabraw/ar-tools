"""Materialize the per-keyword-per-day date axis + recompute status.

Organic Rank Tracker (Module #4), M3. Reads the raw GSC query×date dump
(gsc_query_daily), writes exactly one rank_keyword_metrics row per active
tracked keyword per day over a trailing window — leaving gsc_position NULL on
days GSC returned nothing so the trendline can render the gap — then recomputes
each keyword's status.

Runs as a `gsc_materialize` job chained after each successful ingest, and on
demand (keyword added / manual trigger). See PRD §6, §7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import rank_status

logger = logging.getLogger(__name__)


@dataclass
class MaterializeResult:
    status: str  # 'ok' | 'failed'
    keywords: int
    rows: int
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def index_gsc_rows(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Index raw gsc_query_daily rows by (lowercased query, date iso)."""
    index: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row["query"]).lower(), str(row["date"]))
        index[key] = row
    return index


def build_keyword_axis(
    keyword_id: str,
    keyword: str,
    dates: list[date],
    gsc_index: dict[tuple[str, str], dict],
) -> list[dict]:
    """One rank_keyword_metrics record per date; absent days carry NULL position.

    An absent day is a zero-impression day: clicks/impressions/ctr = 0 and
    gsc_position = None (the stored gap). tracked_rank is left untouched here
    (DataForSEO writes it in M4) — we omit it so an upsert doesn't clobber it.
    """
    kw = keyword.lower()
    records: list[dict] = []
    for d in dates:
        hit = gsc_index.get((kw, d.isoformat()))
        records.append(
            {
                "keyword_id": keyword_id,
                "date": d.isoformat(),
                "clicks": int(hit.get("clicks", 0) or 0) if hit else 0,
                "impressions": int(hit.get("impressions", 0) or 0) if hit else 0,
                "ctr": float(hit.get("ctr", 0) or 0) if hit else 0.0,
                "gsc_position": hit.get("position") if hit else None,
            }
        )
    return records


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def materialize_property(property_id: str, today: Optional[date] = None) -> MaterializeResult:
    """Rebuild the date axis + status for every active keyword of a property."""
    supabase = get_supabase()
    today = today or date.today()
    start = today - timedelta(days=settings.rank_materialize_days)
    dates = date_range(start, today)

    keywords = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("property_id", property_id)
        .eq("active", True)
        .execute()
    )
    if not keywords.data:
        return MaterializeResult(status="ok", keywords=0, rows=0)

    raw = (
        supabase.table("gsc_query_daily")
        .select("query, date, clicks, impressions, ctr, position")
        .eq("property_id", property_id)
        .gte("date", start.isoformat())
        .lte("date", today.isoformat())
        .execute()
    )
    gsc_index = index_gsc_rows(raw.data or [])

    total_rows = 0
    now_iso = "now()"
    try:
        for kw in keywords.data:
            records = build_keyword_axis(kw["id"], kw["keyword"], dates, gsc_index)
            if records:
                supabase.table("rank_keyword_metrics").upsert(
                    records, on_conflict="keyword_id,date"
                ).execute()
                total_rows += len(records)

            series = [(r["date"], r["gsc_position"]) for r in records]
            status = rank_status.compute_status(series)
            supabase.table("tracked_keywords").update(
                {"status": status, "status_updated_at": now_iso, "updated_at": now_iso}
            ).eq("id", kw["id"]).execute()
    except Exception as exc:
        logger.error("rank_materialize_failed", extra={"property_id": property_id, "error": str(exc)})
        return MaterializeResult(status="failed", keywords=len(keywords.data), rows=total_rows, error=str(exc))

    logger.info(
        "rank_materialize_complete",
        extra={"property_id": property_id, "keywords": len(keywords.data), "rows": total_rows},
    )
    return MaterializeResult(status="ok", keywords=len(keywords.data), rows=total_rows)


def enqueue_materialize(property_id: str) -> None:
    """Enqueue a gsc_materialize job (deduped against pending ones)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gsc_materialize")
        .eq("entity_id", property_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {
            "job_type": "gsc_materialize",
            "entity_id": property_id,
            "payload": {"property_id": property_id},
        }
    ).execute()


async def run_gsc_materialize_job(job: dict) -> None:
    """async_jobs handler for job_type='gsc_materialize'."""
    payload = job.get("payload") or {}
    property_id = payload.get("property_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not property_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing property_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = materialize_property(property_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"keywords": result.keywords, "rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
