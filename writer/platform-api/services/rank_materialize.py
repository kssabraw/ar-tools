"""Materialize the per-keyword-per-day date axis + recompute status/source.

Organic Rank Tracker (Module #4). Reads the raw GSC query×date dump
(gsc_query_daily) for the client's verified property — if any — and writes one
rank_keyword_metrics row per active keyword per day over a trailing window,
leaving gsc_position NULL on days GSC returned nothing (the stored gap). Then
recomputes each keyword's status + source, blending in DataForSEO tracked_rank
that the weekly fallback job wrote (without ever overwriting it).

Keywords are CLIENT-anchored (GSC property optional), so this runs per client.
Runs as a `gsc_materialize` job (chained after ingest / DataForSEO refresh, and
on keyword add) and on demand. See PRD §2, §6, §7.
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
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def index_gsc_rows(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Index raw gsc_query_daily rows by (lowercased query, date iso)."""
    index: dict[tuple[str, str], dict] = {}
    for row in rows:
        index[(str(row["query"]).lower(), str(row["date"]))] = row
    return index


def build_keyword_axis(
    keyword_id: str,
    keyword: str,
    dates: list[date],
    gsc_index: dict[tuple[str, str], dict],
) -> list[dict]:
    """One rank_keyword_metrics record per date; absent days carry NULL position.

    tracked_rank is intentionally omitted so the upsert never clobbers the
    DataForSEO value (different job, different column — PRD §5).
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


def classify_source(merged_rows: list[dict]) -> str:
    """tracked_keywords.source from what data the keyword actually has."""
    has_gsc = any(r.get("gsc_position") is not None for r in merged_rows)
    has_df = any(r.get("tracked_rank") is not None for r in merged_rows)
    if has_gsc and has_df:
        return "both"
    if has_df:
        return "dataforseo"
    return "gsc"  # GSC-only or no-data-yet (the default)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _verified_property_id(supabase, client_id: str) -> Optional[str]:
    res = (
        supabase.table("gsc_properties")
        .select("id")
        .eq("client_id", client_id)
        .eq("access_status", "ok")
        .order("created_at")
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def materialize_client(client_id: str, today: Optional[date] = None) -> MaterializeResult:
    """Rebuild the date axis + status/source for every active keyword of a client."""
    supabase = get_supabase()
    today = today or date.today()
    start = today - timedelta(days=settings.rank_materialize_days)
    dates = date_range(start, today)
    coverage = settings.rank_gsc_coverage_days

    keywords = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    )
    if not keywords.data:
        return MaterializeResult(status="ok", keywords=0, rows=0)
    keyword_ids = [k["id"] for k in keywords.data]

    # GSC data (only if the client has a verified property).
    property_id = _verified_property_id(supabase, client_id)
    gsc_index: dict[tuple[str, str], dict] = {}
    if property_id:
        raw = (
            supabase.table("gsc_query_daily")
            .select("query, date, clicks, impressions, ctr, position")
            .eq("property_id", property_id)
            .gte("date", start.isoformat())
            .lte("date", today.isoformat())
            .execute()
        )
        gsc_index = index_gsc_rows(raw.data or [])

    # Existing DataForSEO ranks (weekly fallback wrote these); blend for status.
    df_rows = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, tracked_rank")
        .in_("keyword_id", keyword_ids)
        .gte("date", start.isoformat())
        .execute()
    ).data or []
    df_by_kw: dict[str, dict[str, int]] = {}
    for r in df_rows:
        if r.get("tracked_rank") is not None:
            df_by_kw.setdefault(r["keyword_id"], {})[str(r["date"])] = r["tracked_rank"]

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

            # Merge in DataForSEO ranks to pick the source + status.
            kw_df = df_by_kw.get(kw["id"], {})
            merged = [{**r, "tracked_rank": kw_df.get(r["date"])} for r in records]
            source = classify_source(merged)
            primary = rank_status.determine_primary_source(merged, today, coverage)
            if primary == "dataforseo":
                series = [(r["date"], r.get("tracked_rank")) for r in merged]
            else:
                series = [(r["date"], r.get("gsc_position")) for r in merged]
            status = rank_status.compute_status(series)

            supabase.table("tracked_keywords").update(
                {"status": status, "source": source, "status_updated_at": now_iso, "updated_at": now_iso}
            ).eq("id", kw["id"]).execute()
    except Exception as exc:
        logger.error("rank_materialize_failed", extra={"client_id": client_id, "error": str(exc)})
        return MaterializeResult(status="failed", keywords=len(keywords.data), rows=total_rows, error=str(exc))

    logger.info(
        "rank_materialize_complete",
        extra={"client_id": client_id, "keywords": len(keywords.data), "rows": total_rows},
    )
    return MaterializeResult(status="ok", keywords=len(keywords.data), rows=total_rows)


def enqueue_materialize(client_id: str) -> None:
    """Enqueue a gsc_materialize job (deduped against pending ones)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gsc_materialize")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "gsc_materialize", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()


async def run_gsc_materialize_job(job: dict) -> None:
    """async_jobs handler for job_type='gsc_materialize'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = materialize_client(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"keywords": result.keywords, "rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
