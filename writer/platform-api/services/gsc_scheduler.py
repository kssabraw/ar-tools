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


async def gsc_scheduler() -> None:
    """Background loop: daily GSC ingest enqueue + weekly DataForSEO rank enqueue."""
    interval = settings.gsc_scheduler_poll_interval_seconds
    hour = settings.gsc_ingest_hour_utc
    weekday = settings.dataforseo_rank_weekday
    last_run_date: Optional[date] = None
    last_df_date: Optional[date] = None
    logger.info("gsc_scheduler.started", extra={"poll_interval_s": interval, "hour_utc": hour})
    while True:
        await asyncio.sleep(interval)
        try:
            now = datetime.now(timezone.utc)
            if should_run(now, last_run_date, hour):
                enqueue_due_ingests()
                enqueue_due_market()
                last_run_date = now.date()
            # Weekly DataForSEO fallback, same daily-hour guard but only on the
            # configured weekday.
            if now.weekday() == weekday and should_run(now, last_df_date, hour):
                enqueue_due_dataforseo()
                last_df_date = now.date()
        except Exception as exc:
            logger.error("gsc_scheduler.unhandled", extra={"error": str(exc)})
