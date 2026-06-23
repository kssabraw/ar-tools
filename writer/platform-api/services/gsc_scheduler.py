"""GSC ingest scheduler — daily enqueue loop.

Organic Rank Tracker (Module #4), M2. The suite's shared scheduler mechanism
(suite roadmap Open Item #1, decided 2026-06-22): an in-process asyncio loop in
the already-running platform-api that, once per day after `gsc_ingest_hour_utc`,
enqueues a `gsc_ingest` async_jobs row for each verified property. The existing
job_worker then executes them. Zero new infrastructure; a missed day (service
down at fire time) self-heals via the ingest's trailing re-pull window.

This is the reusable spine for later scheduled trackers (Maps #5, content
scheduler #7) — add their enqueue passes here rather than introducing new infra.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def should_run(now: datetime, last_run_date: Optional[date], hour_utc: int) -> bool:
    """True when it's past today's target hour and we haven't run today yet."""
    if now.hour < hour_utc:
        return False
    return last_run_date is None or last_run_date < now.date()


def _has_pending_ingest(supabase, property_id: str) -> bool:
    """Avoid stacking duplicate jobs for the same property."""
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gsc_ingest")
        .eq("entity_id", property_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    return bool(existing.data)


def enqueue_due_ingests() -> int:
    """Enqueue a gsc_ingest job for every verified property. Returns the count."""
    supabase = get_supabase()
    props = (
        supabase.table("gsc_properties")
        .select("id")
        .eq("access_status", "ok")
        .execute()
    )
    enqueued = 0
    for prop in props.data or []:
        property_id = prop["id"]
        if _has_pending_ingest(supabase, property_id):
            continue
        supabase.table("async_jobs").insert(
            {
                "job_type": "gsc_ingest",
                "entity_id": property_id,
                "payload": {"property_id": property_id},
            }
        ).execute()
        enqueued += 1
    if enqueued:
        logger.info("gsc_scheduler.enqueued", extra={"jobs": enqueued})
    return enqueued


def enqueue_due_dataforseo() -> int:
    """Weekly: enqueue a DataForSEO rank job for each client with active keywords.

    The job itself skips keywords GSC already covers, so this is cheap for
    GSC-connected clients and the sole rank source for clients without GSC.
    """
    from services.dataforseo_rank import enqueue_dataforseo_rank

    supabase = get_supabase()
    rows = (
        supabase.table("tracked_keywords")
        .select("client_id")
        .eq("active", True)
        .execute()
    )
    client_ids = {r["client_id"] for r in (rows.data or [])}
    for client_id in client_ids:
        enqueue_dataforseo_rank(client_id)
    if client_ids:
        logger.info("gsc_scheduler.dataforseo_enqueued", extra={"clients": len(client_ids)})
    return len(client_ids)


def enqueue_due_serp_snapshots() -> int:
    """Weekly: enqueue a competitive SERP snapshot capture per client with
    active keywords (piggybacks the DataForSEO rank weekday). The job captures a
    dated snapshot per keyword for ranking-drop diagnosis."""
    from services.serp_snapshot import enqueue_serp_snapshot

    supabase = get_supabase()
    rows = supabase.table("tracked_keywords").select("client_id").eq("active", True).execute()
    client_ids = {r["client_id"] for r in (rows.data or [])}
    for client_id in client_ids:
        enqueue_serp_snapshot(client_id)
    if client_ids:
        logger.info("gsc_scheduler.serp_snapshots_enqueued", extra={"clients": len(client_ids)})
    return len(client_ids)


def enqueue_due_market() -> int:
    """Daily-triggered, monthly-effective: enqueue a market refresh per client
    with active keywords. The job only re-fetches keywords whose cached market
    data is missing or older than the refresh window, so this is cheap."""
    from services.keyword_market import enqueue_keyword_market

    supabase = get_supabase()
    rows = supabase.table("tracked_keywords").select("client_id").eq("active", True).execute()
    client_ids = {r["client_id"] for r in (rows.data or [])}
    for client_id in client_ids:
        enqueue_keyword_market(client_id)
    return len(client_ids)


def enqueue_due_page_ingest() -> int:
    """Weekly: enqueue a query×page ingest for each verified property."""
    supabase = get_supabase()
    props = supabase.table("gsc_properties").select("id").eq("access_status", "ok").execute()
    enqueued = 0
    for prop in props.data or []:
        property_id = prop["id"]
        existing = (
            supabase.table("async_jobs").select("id")
            .eq("job_type", "gsc_page_ingest").eq("entity_id", property_id)
            .in_("status", ["pending", "running"]).limit(1).execute()
        )
        if existing.data:
            continue
        supabase.table("async_jobs").insert(
            {"job_type": "gsc_page_ingest", "entity_id": property_id, "payload": {"property_id": property_id}}
        ).execute()
        enqueued += 1
    return enqueued


def enqueue_due_reports() -> int:
    """Daily: enqueue a rank_report job for each client whose schedule is due."""
    from datetime import date

    from services.rank_report import enqueue_rank_report, is_report_due

    supabase = get_supabase()
    configs = (
        supabase.table("rank_report_config").select("*").neq("mode", "as_needed").execute()
    ).data or []
    today = date.today()
    due = 0
    for cfg in configs:
        if is_report_due(cfg, today):
            enqueue_rank_report(cfg["client_id"])
            due += 1
    if due:
        logger.info("gsc_scheduler.reports_enqueued", extra={"clients": due})
    return due


async def gsc_scheduler() -> None:
    """Background loop: daily GSC ingest enqueue + weekly DataForSEO rank enqueue
    + weekly Maps geo-grid scans, and a per-tick poll of in-flight Maps scans."""
    from services.local_dominator import enqueue_due_maps_scans, poll_pending_maps_scans

    interval = settings.gsc_scheduler_poll_interval_seconds
    hour = settings.gsc_ingest_hour_utc
    weekday = settings.dataforseo_rank_weekday
    maps_weekday = settings.maps_scan_weekday
    last_run_date: Optional[date] = None
    last_df_date: Optional[date] = None
    last_maps_date: Optional[date] = None
    logger.info("gsc_scheduler.started", extra={"poll_interval_s": interval, "hour_utc": hour})
    while True:
        await asyncio.sleep(interval)
        try:
            now = datetime.now(timezone.utc)
            if should_run(now, last_run_date, hour):
                enqueue_due_ingests()
                enqueue_due_market()
                enqueue_due_reports()
                last_run_date = now.date()
            # Weekly DataForSEO fallback + query×page ingest, same daily-hour
            # guard but only on the configured weekday.
            if now.weekday() == weekday and should_run(now, last_df_date, hour):
                enqueue_due_dataforseo()
                enqueue_due_page_ingest()
                enqueue_due_serp_snapshots()
                last_df_date = now.date()
            # Weekly Maps geo-grid scans (Module #5) on their own weekday.
            if now.weekday() == maps_weekday and should_run(now, last_maps_date, hour):
                enqueue_due_maps_scans()
                last_maps_date = now.date()
            # Advance any in-flight Maps scans every tick (non-blocking GETs).
            await poll_pending_maps_scans()
        except Exception as exc:
            logger.error("gsc_scheduler.unhandled", extra={"error": str(exc)})
