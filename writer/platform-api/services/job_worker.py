"""Async job worker — polls async_jobs table and processes website_scrape jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config import settings
from db.supabase_client import get_supabase
from services.brand_scan import run_brand_scan_job
from services.brand_report import run_brand_report_job
from services.dataforseo_rank import run_dataforseo_rank_job
from services.gsc_ingest import run_gsc_ingest_job, run_gsc_page_ingest_job
from services.gsc_research import run_gsc_research_job
from services.keyword_market import run_keyword_market_job
from services.local_seo_service import (
    run_generate_job,
    run_reoptimize_page_job,
    run_reoptimize_url_job,
)
from services.local_seo_silo import run_silo_plan_job
from services.rank_location import run_rank_location_derive_job
from services.service_page_plan import run_service_plan_job
from services.rank_report import run_rank_report_job
from services.rank_materialize import run_gsc_materialize_job
from services.notifications import run_notification_dispatch_job
from services.client_report import run_client_report_job
from services.reopt_planner import run_reopt_plan_job
from services.serp_snapshot import run_serp_snapshot_job
from services.local_dominator import run_maps_scan_job
from services.maps_report import run_maps_report_job
from services.maps_analyzer import run_maps_analyze_job
from services.competitor_gbp import run_competitor_gbp_job
from services.review_analytics import run_review_intel_job
from services.page_structure_scraper import analyze_page_structure
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


def _plan_reap(attempts: int, max_attempts: int) -> tuple[dict, str]:
    """Decide how to reap a job stuck in 'running': re-queue (back to pending) while
    retry attempts remain, else mark it failed. In-process jobs aren't resumable, so
    a re-queued orphan is simply re-claimed and retried — self-healing the common
    redeploy-mid-run case. Pure; unit-tested."""
    if attempts < max_attempts:
        return {"status": "pending", "started_at": None}, "requeued"
    return {
        "status": "failed",
        "error": "stale_timeout: orphaned mid-run (likely a worker restart) and reaped",
        "completed_at": "now()",
    }, "failed"


async def _reap_stale_jobs() -> None:
    """Sweep jobs stuck in 'running' past the stale timeout and re-queue or fail
    them (see `_plan_reap`). Guards each update on status='running' so a job that
    finished between the read and write is never stomped. Best-effort — a failure
    here must never break the worker loop."""
    timeout_min = settings.job_stale_timeout_minutes
    if timeout_min <= 0:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_min)).isoformat()
    supabase = get_supabase()
    try:
        stale = (
            supabase.table("async_jobs")
            .select("id, job_type, attempts, max_attempts")
            .eq("status", "running")
            .lt("started_at", cutoff)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("job_worker.reap_query_failed", extra={"error": str(exc)})
        return

    for job in stale:
        update, outcome = _plan_reap(job.get("attempts", 0), job.get("max_attempts", 2))
        try:
            result = (
                supabase.table("async_jobs")
                .update(update)
                .eq("id", job["id"])
                .eq("status", "running")  # don't stomp a job that just completed
                .execute()
            )
            if result.data:
                logger.warning(
                    "job_worker.reaped_stale_job",
                    extra={
                        "job_id": job["id"],
                        "job_type": job.get("job_type"),
                        "outcome": outcome,
                        "attempts": job.get("attempts", 0),
                        "timeout_min": timeout_min,
                    },
                )
        except Exception as exc:
            logger.error(
                "job_worker.reap_update_failed",
                extra={"job_id": job["id"], "error": str(exc)},
            )


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


async def _run_page_structure_scrape(job: dict) -> None:
    """Execute a page_structure_scrape job for one of a client's reference pages.

    Fetches the page, strips chrome, analyzes its structure, and merges the
    result into clients.page_structures[page_type]. The merge is a read-modify-
    write of the JSONB column — safe because the worker processes one job per
    tick (no concurrent writers to the same client row)."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    page_type = payload.get("page_type")
    url = payload.get("url")
    job_id = job["id"]

    logger.info(
        "page_structure_scrape_started",
        extra={"job_id": job_id, "client_id": client_id, "page_type": page_type, "url": url},
    )

    supabase = get_supabase()

    def _store(entry: dict) -> None:
        """Merge `entry` into page_structures[page_type] without clobbering siblings."""
        current = (
            supabase.table("clients")
            .select("page_structures")
            .eq("id", client_id)
            .single()
            .execute()
        )
        structures = (current.data or {}).get("page_structures") or {}
        existing = structures.get(page_type) or {}
        existing.update(entry)
        structures[page_type] = existing
        supabase.table("clients").update({"page_structures": structures}).eq("id", client_id).execute()

    try:
        html = await scrapeowl_fetch(url, timeout=45)
        if not html:
            raise ValueError("ScrapeOwl returned empty HTML")

        analysis = await analyze_page_structure(html, page_type)

        _store(
            {
                "url": url,
                "status": "complete",
                "error": None,
                "analysis": analysis,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": analysis, "completed_at": "now()"}
        ).eq("id", job_id).execute()

        logger.info(
            "page_structure_scrape_complete",
            extra={"job_id": job_id, "client_id": client_id, "page_type": page_type},
        )
    except Exception as exc:
        logger.warning(
            "page_structure_scrape_failed",
            extra={"job_id": job_id, "client_id": client_id, "page_type": page_type, "error": str(exc)},
        )
        try:
            _store({"url": url, "status": "failed", "error": str(exc)[:500]})
        except Exception:
            logger.error("page_structure_scrape_store_failed", extra={"job_id": job_id})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


async def _process_job(job: dict) -> None:
    job_type = job.get("job_type")
    if job_type == "website_scrape":
        await _run_website_scrape(job)
    elif job_type == "page_structure_scrape":
        await _run_page_structure_scrape(job)
    elif job_type == "silo_dedup":
        await process_silo_dedup_job(job)
    elif job_type == "gsc_ingest":
        await run_gsc_ingest_job(job)
    elif job_type == "gsc_page_ingest":
        await run_gsc_page_ingest_job(job)
    elif job_type == "gsc_materialize":
        await run_gsc_materialize_job(job)
    elif job_type == "dataforseo_rank":
        await run_dataforseo_rank_job(job)
    elif job_type == "keyword_market":
        await run_keyword_market_job(job)
    elif job_type == "gsc_research":
        await run_gsc_research_job(job)
    elif job_type == "rank_report":
        await run_rank_report_job(job)
    elif job_type == "serp_snapshot":
        await run_serp_snapshot_job(job)
    elif job_type == "maps_scan":
        await run_maps_scan_job(job)
    elif job_type == "maps_report":
        await run_maps_report_job(job)
    elif job_type == "maps_analyze":
        await run_maps_analyze_job(job)
    elif job_type == "competitor_gbp":
        await run_competitor_gbp_job(job)
    elif job_type == "review_intel":
        await run_review_intel_job(job)
    elif job_type == "local_seo_silo":
        await run_silo_plan_job(job)
    elif job_type == "local_seo_generate":
        await run_generate_job(job)
    elif job_type == "local_seo_reoptimize_url":
        await run_reoptimize_url_job(job)
    elif job_type == "local_seo_reoptimize_page":
        await run_reoptimize_page_job(job)
    elif job_type == "service_page_plan":
        await run_service_plan_job(job)
    elif job_type == "rank_location_derive":
        await run_rank_location_derive_job(job)
    elif job_type == "brand_scan":
        await run_brand_scan_job(job)
    elif job_type == "brand_report":
        await run_brand_report_job(job)
    elif job_type == "notification_dispatch":
        await run_notification_dispatch_job(job)
    elif job_type == "reopt_plan":
        await run_reopt_plan_job(job)
    elif job_type == "client_report":
        await run_client_report_job(job)
    else:
        logger.warning("job_worker.unknown_job_type", extra={"job_type": job_type})


async def job_worker() -> None:
    """Background loop: poll async_jobs every N seconds and process one job per tick."""
    interval = settings.job_worker_poll_interval_seconds
    logger.info("job_worker.started", extra={"poll_interval_s": interval})
    while True:
        await asyncio.sleep(interval)
        try:
            await _reap_stale_jobs()
            job = await _claim_next_job()
            if job:
                logger.info(
                    "async_job_claimed",
                    extra={"job_id": job["id"], "job_type": job.get("job_type")},
                )
                await _process_job(job)
        except Exception as exc:
            logger.error("job_worker.unhandled", extra={"error": str(exc)})
