"""Async job worker — polls async_jobs table and processes website_scrape jobs."""

from __future__ import annotations

import asyncio
import logging

from config import settings
from db.supabase_client import get_supabase
from services.silo_dedup import process_silo_dedup_job
from services.website_scraper import llm_extract_website_data, scrapeowl_fetch

logger = logging.getLogger(__name__)


async def _claim_next_job() -> dict | None:
    """Claim the next pending job using SELECT FOR UPDATE SKIP LOCKED via RPC."""
    supabase = get_supabase()
    try:
        # Use a raw SQL claim via supabase rpc or direct table operations.
        # supabase-py doesn't support FOR UPDATE SKIP LOCKED directly, so we
        # fetch the oldest pending job and immediately mark it running.
        result = (
            supabase.table("async_jobs")
            .select("*")
            .eq("status", "pending")
            .order("scheduled_at")
            .limit(1)
            .execute()
        )
        jobs = result.data or []
        if not jobs:
            return None

        job = jobs[0]
        # Only process if attempts < max_attempts
        if job.get("attempts", 0) >= job.get("max_attempts", 2):
            return None

        # Attempt to claim it (race condition acceptable in v1 with single instance)
        update_result = (
            supabase.table("async_jobs")
            .update(
                {
                    "status": "running",
                    "attempts": job.get("attempts", 0) + 1,
                    "started_at": "now()",
                }
            )
            .eq("id", job["id"])
            .eq("status", "pending")  # guard against double-claim
            .execute()
        )
        if not update_result.data:
            return None  # Another instance claimed it first
        return update_result.data[0]
    except Exception as exc:
        logger.error("job_worker.claim_failed", extra={"error": str(exc)})
        return None


async def _run_website_scrape(job: dict) -> None:
    """Execute a website_scrape job."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    website_url = payload.get("website_url")
    job_id = job["id"]

    logger.info(
        "website_scrape_started",
        extra={"job_id": job_id, "client_id": client_id, "url": website_url},
    )

    supabase = get_supabase()
    try:
        html = await scrapeowl_fetch(website_url, timeout=45)
        if not html:
            raise ValueError("ScrapeOwl returned empty HTML")

        result = await llm_extract_website_data(html)

        supabase.table("clients").update(
            {
                "website_analysis": result,
                "website_analysis_status": "complete",
                "website_analysis_error": None,
            }
        ).eq("id", client_id).execute()

        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()

        logger.info(
            "website_scrape_complete", extra={"job_id": job_id, "client_id": client_id}
        )

    except Exception as exc:
        logger.warning(
            "website_scrape_failed",
            extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
        )
        supabase.table("clients").update(
            {
                "website_analysis_status": "failed",
                "website_analysis_error": str(exc)[:500],
            }
        ).eq("id", client_id).execute()

        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


async def _process_job(job: dict) -> None:
    job_type = job.get("job_type")
    if job_type == "website_scrape":
        await _run_website_scrape(job)
    elif job_type == "silo_dedup":
        await process_silo_dedup_job(job)
    else:
        logger.warning("job_worker.unknown_job_type", extra={"job_type": job_type})


async def job_worker() -> None:
    """Background loop: poll async_jobs every N seconds and process one job per tick."""
    interval = settings.job_worker_poll_interval_seconds
    logger.info("job_worker.started", extra={"poll_interval_s": interval})
    while True:
        await asyncio.sleep(interval)
        try:
            job = await _claim_next_job()
            if job:
                logger.info(
                    "async_job_claimed",
                    extra={"job_id": job["id"], "job_type": job.get("job_type")},
                )
                await _process_job(job)
        except Exception as exc:
            logger.error("job_worker.unhandled", extra={"error": str(exc)})
