"""Async job worker — polls async_jobs table and processes website_scrape jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config import settings
from db.supabase_client import get_supabase
from services import activity
from services.brand_scan import run_brand_scan_job
from services.brand_report import run_brand_report_job
from services.brand_voice_service import run_brand_voice_scan_job
from services.icp_service import run_icp_scan_job
from services.dataforseo_rank import run_dataforseo_rank_job
from services.gbp_metrics_ingest import run_gbp_metrics_ingest_job
from services.gsc_ingest import run_gsc_ingest_job, run_gsc_page_ingest_job
from services.gsc_research import run_gsc_research_job
from services.keyword_market import run_keyword_market_job
from services.local_seo_service import (
    run_generate_job,
    run_local_seo_action_job,
    run_reoptimize_page_job,
    run_reoptimize_url_job,
)
from services.local_seo_silo import run_silo_plan_job
from services import ecommerce_service
from services.rank_location import run_rank_location_derive_job
from services.service_page_plan import run_service_plan_job
from services.rank_analysis_report import run_rank_keyword_report_job
from services.rank_report import run_rank_report_job
from services.rank_materialize import run_gsc_materialize_job
from services.citation_check import run_citation_check_job
from services.competitor_intel import run_competitor_intel_job
from services.deliverables_sheet import (
    run_log_job as run_deliverables_log_job,
    run_notes_scan_job as run_deliverable_notes_scan_job,
    run_provision_job as run_deliverables_provision_job,
)
from services.domain_intel import run_domain_overview_job, run_keyword_gap_job, run_link_gap_job
from services.github_infer import run_github_infer_job
from services.blog_media.pipeline import run_blog_media_publish_job
from services.keyword_research import run_keyword_research_job
from services.freeze import FREEZE_GATED_JOB_TYPES, is_frozen, job_client_id, run_freeze_check_job
from services.page_backlink_intel import run_page_backlink_job
from services.notifications import run_notification_dispatch_job
from services.client_report import run_client_report_job
from services.reopt_planner import run_reopt_plan_job
from services.asana_monthly import run_asana_monthly_job
from services.asana_push import run_asana_push_job
from services.task_import import run_import_job as run_task_import_job
from services.task_monthly import run_task_month_job
from services.task_workload import run_due_sweep_job
from services.qa_service import run_qa_review_job
from services.serp_snapshot import run_serp_snapshot_job
from services.local_dominator import run_maps_scan_job
from services.maps_report import run_maps_image_backfill_job, run_maps_report_job
from services.maps_analyzer import run_maps_analyze_job
from services.competitor_gbp import run_competitor_gbp_job
from services.review_analytics import run_review_intel_job
from services.backlink_intel import run_backlink_intel_job
from services.backlink_explorer import run_backlink_snapshot_job
from services.content_intel import run_content_intel_job
from services.leadoff_actions import (
    run_scout_job as run_leadoff_scout_job,
    run_tryout_job as run_leadoff_tryout_job,
)
from services.leadoff_ai_probe import run_ai_probe_job as run_leadoff_ai_probe_job
from services.leadoff_permits import run_permits_job as run_leadoff_permits_job
from services.leadoff_geocode import run_geocode_job as run_leadoff_geocode_job
from services.leadoff_signals import run_signal_refresh_job as run_leadoff_signal_refresh_job
from services.leadoff_income import run_income_backfill_job as run_leadoff_income_backfill_job
from services.leadoff_counties import run_county_backfill_job as run_leadoff_county_backfill_job
from services.leadoff_finder import run_city_finder_job as run_leadoff_city_finder_job
from services.local_relevance import run_local_relevance_job
from services.page_structure_scraper import analyze_page_structure
from services.silo_dedup import process_silo_dedup_job
from services.strategist import run_strategy_review_job
from services.internal_linking import run_internal_link_analyze_job, run_internal_link_apply_job
from services.syndication_service import run_syndication_item_job, run_syndication_scan_job
from services.content_batch import run_content_batch_item_job
from services.website_scraper import llm_extract_website_data, scrapeowl_fetch

logger = logging.getLogger(__name__)

# Ids of async_jobs THIS process is currently executing (populated when a lane
# claims a job, cleared when the handler settles — see `job_worker`). On a
# graceful shutdown (redeploy) these are requeued immediately via
# `drain_inflight_jobs` so the next container picks them up, instead of the
# interrupted job sitting 'running' until the stale-job reaper heals it (up to
# job_stale_timeout_minutes later). Per-process, NOT global: a rolling redeploy
# briefly runs old + new containers at once, and we must never requeue a job the
# sibling container just claimed — so drain only touches ids in this set.
_inflight_jobs: set[str] = set()


async def _claim_next_job(job_types: list[str] | None = None) -> dict | None:
    """Claim the oldest pending job (optionally restricted to `job_types` — the
    interactive lane's filter) and atomically mark it running."""
    supabase = get_supabase()
    try:
        # supabase-py doesn't support FOR UPDATE SKIP LOCKED directly, so we
        # fetch the oldest pending job and immediately mark it running.
        query = supabase.table("async_jobs").select("*").eq("status", "pending")
        if job_types:
            query = query.in_("job_type", job_types)
        result = query.order("scheduled_at").limit(1).execute()
        jobs = result.data or []
        if not jobs:
            return None

        job = jobs[0]
        # Only process if attempts < max_attempts
        if job.get("attempts", 0) >= job.get("max_attempts", 2):
            return None

        # Atomic claim: the status='pending' guard means when the two in-process
        # lanes race for the same row, exactly one PATCH matches — the loser gets
        # an empty result and simply polls again.
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


def stale_timeout_for(job_type: str | None) -> int:
    """The stale timeout (minutes) for a job type — the per-type override when
    one is configured (legitimately long jobs: rank_keyword_report and
    gsc_page_ingest both grazed the 30-min default in prod and got reaped
    mid-run), else the global default. Pure."""
    overrides = settings.job_stale_timeout_overrides or {}
    try:
        return int(overrides.get(job_type or "", settings.job_stale_timeout_minutes))
    except (TypeError, ValueError):
        return settings.job_stale_timeout_minutes


def _past_timeout(started_at, now: datetime, timeout_min: int) -> bool:
    """Whether a job's started_at is older than timeout_min. Unparseable/missing
    started_at counts as past (matches the reaper's historical behavior). Pure."""
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return started < now - timedelta(minutes=timeout_min)


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
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(minutes=timeout_min)).isoformat()
    supabase = get_supabase()
    try:
        stale = (
            supabase.table("async_jobs")
            .select("id, job_type, attempts, max_attempts, started_at")
            .eq("status", "running")
            .lt("started_at", cutoff)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("job_worker.reap_query_failed", extra={"error": str(exc)})
        return

    for job in stale:
        # The query cutoff uses the global default; a type with a LONGER
        # override is only reaped once it's past its own timeout.
        per_type = stale_timeout_for(job.get("job_type"))
        if per_type > timeout_min and not _past_timeout(job.get("started_at"), now, per_type):
            continue
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


async def drain_inflight_jobs() -> None:
    """Graceful-shutdown handoff: requeue every job THIS process is still mid-run
    so the next container claims it immediately, instead of the interrupted job
    sitting 'running' until the stale-job reaper heals it (up to
    job_stale_timeout_minutes later — the source of the "every redeploy stalls
    in-progress work" symptom).

    A restart is not the job's fault, so the retry attempt the claim consumed is
    REFUNDED (attempts−1, floored at 0). Without the refund, a couple of
    back-to-back redeploys would drive attempts to max_attempts and strand the
    job unclaimable in 'pending' forever (the claim skips attempts>=max). The
    reaper deliberately does NOT refund — a job that trips the reaper may be
    genuinely hung, and consuming attempts there is what eventually fails it;
    drain only runs on a clean shutdown, where the interruption is definitely us.

    MUST be called AFTER the worker tasks are cancelled and awaited (see
    lifespan): the worker loop keeps a cancelled job's id registered exactly so
    this can find it, and draining while a lane still runs would let it claim a
    fresh job right after the drain — orphaning that one until the reaper.

    Each update is guarded on status='running' so a job that settled between the
    read and the write is never stomped (its terminal write wins), and on id so a
    sibling container's freshly-claimed jobs are untouched. Best-effort — a drain
    failure must never block shutdown."""
    job_ids = list(_inflight_jobs)
    if not job_ids:
        return
    supabase = get_supabase()
    drained = 0
    for job_id in job_ids:
        try:
            row = (
                supabase.table("async_jobs")
                .select("attempts")
                .eq("id", job_id)
                .single()
                .execute()
            ).data or {}
            attempts = max(0, int(row.get("attempts") or 0) - 1)
            result = (
                supabase.table("async_jobs")
                .update({"status": "pending", "started_at": None, "attempts": attempts})
                .eq("id", job_id)
                .eq("status", "running")  # don't stomp a job that just completed
                .execute()
            )
            if result.data:
                drained += 1
        except Exception as exc:
            logger.error(
                "job_worker.drain_failed",
                extra={"job_id": job_id, "error": str(exc)},
            )
    if drained:
        logger.warning(
            "job_worker.drained_inflight_jobs",
            extra={"drained": drained, "of": len(job_ids)},
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

        # If the cheap datacenter fetch captured nothing, the site likely
        # bot-blocked it (a WordPress/CDN wall served an empty shell). Retry
        # ONCE with JS rendering + premium residential proxies — the thing that
        # gets past those walls — and keep the retry only if it actually found
        # content. Bounded cost: only fires on an empty first pass.
        retry_error = None
        retry_html_len = None
        retry_raw_headings = None
        if settings.page_structure_premium_fallback and not (analysis.get("outline") or []):
            logger.info(
                "page_structure_scrape_premium_retry",
                extra={"job_id": job_id, "client_id": client_id, "page_type": page_type},
            )
            try:
                html2 = await scrapeowl_fetch(url, timeout=90, render_js=True, premium=True)
                retry_html_len = len(html2 or "")
                if html2:
                    from services.page_structure_scraper import count_headings
                    retry_raw_headings = count_headings(html2)
                    analysis2 = await analyze_page_structure(html2, page_type)
                    if analysis2.get("outline"):
                        analysis = analysis2
            except Exception as exc:
                retry_error = str(exc)[:500]
                logger.warning(
                    "page_structure_scrape_premium_retry_failed error=%s", str(exc)[:500],
                    extra={"job_id": job_id, "error": str(exc)},
                )

        # A capture that yielded zero sections isn't a usable reference (QA and
        # the writers treat it as "no reference"). Flag it explicitly so it's
        # visible WHY — a silent complete-but-empty entry looks like success but
        # enables nothing. The premium-retry diagnostics (its error / how much
        # HTML it fetched) are stored too so a failure is inspectable.
        empty = not (analysis.get("outline") or [])
        _store(
            {
                "url": url,
                "status": "complete",
                "error": None,
                "empty": empty,
                "retry_error": retry_error,
                "retry_html_len": retry_html_len,
                "retry_raw_headings": retry_raw_headings,
                "note": (
                    "Captured 0 content sections — the page may be blocking our "
                    "scraper or use non-semantic markup. Try a different, "
                    "content-rich reference URL."
                    if empty else None
                ),
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
    # Freeze Protocol gate: content-creating / link-building jobs do not run for
    # a frozen client (Link Building SOP §Freeze). Jobs queued before the freeze
    # fail fast with a clear code; analysis/monitoring jobs keep running.
    if job_type in FREEZE_GATED_JOB_TYPES:
        client_id = job_client_id(job)
        if client_id and is_frozen(client_id):
            logger.warning(
                "job_worker.blocked_by_freeze",
                extra={"job_id": job["id"], "job_type": job_type, "client_id": client_id},
            )
            get_supabase().table("async_jobs").update(
                {"status": "failed", "error": "client_frozen", "completed_at": "now()"}
            ).eq("id", job["id"]).execute()
            return
    if job_type == "freeze_check":
        await run_freeze_check_job(job)
    elif job_type == "citation_check":
        await run_citation_check_job(job)
    elif job_type == "competitor_intel":
        await run_competitor_intel_job(job)
    elif job_type == "page_backlink_intel":
        await run_page_backlink_job(job)
    elif job_type == "website_scrape":
        await _run_website_scrape(job)
    elif job_type == "page_structure_scrape":
        await _run_page_structure_scrape(job)
    elif job_type == "silo_dedup":
        await process_silo_dedup_job(job)
    elif job_type == "gsc_ingest":
        await run_gsc_ingest_job(job)
    elif job_type == "gsc_page_ingest":
        await run_gsc_page_ingest_job(job)
    elif job_type == "gbp_metrics_ingest":
        await run_gbp_metrics_ingest_job(job)
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
    elif job_type == "rank_keyword_report":
        await run_rank_keyword_report_job(job)
    elif job_type == "serp_snapshot":
        await run_serp_snapshot_job(job)
    elif job_type == "maps_scan":
        await run_maps_scan_job(job)
    elif job_type == "maps_report":
        await run_maps_report_job(job)
    elif job_type == "maps_image_backfill":
        await run_maps_image_backfill_job(job)
    elif job_type == "maps_analyze":
        await run_maps_analyze_job(job)
    elif job_type == "competitor_gbp":
        await run_competitor_gbp_job(job)
    elif job_type == "review_intel":
        await run_review_intel_job(job)
    elif job_type == "backlink_intel":
        await run_backlink_intel_job(job)
    elif job_type == "backlink_snapshot":
        await run_backlink_snapshot_job(job)
    elif job_type == "content_intel":
        await run_content_intel_job(job)
    elif job_type == "local_relevance":
        await run_local_relevance_job(job)
    elif job_type == "local_seo_silo":
        await run_silo_plan_job(job)
    elif job_type == "local_seo_generate":
        await run_generate_job(job)
    elif job_type == "local_seo_reoptimize_url":
        await run_reoptimize_url_job(job)
    elif job_type == "local_seo_reoptimize_page":
        await run_reoptimize_page_job(job)
    elif job_type == "local_seo_action":
        await run_local_seo_action_job(job)
    elif job_type == "ecommerce_generate":
        await ecommerce_service.run_generate_job(job)
    elif job_type == "ecommerce_reoptimize_url":
        await ecommerce_service.run_reoptimize_url_job(job)
    elif job_type == "ecommerce_action":
        await ecommerce_service.run_ecommerce_action_job(job)
    elif job_type == "service_page_plan":
        await run_service_plan_job(job)
    elif job_type == "rank_location_derive":
        await run_rank_location_derive_job(job)
    elif job_type == "brand_scan":
        await run_brand_scan_job(job)
    elif job_type == "brand_voice_scan":
        await run_brand_voice_scan_job(job)
    elif job_type == "icp_scan":
        await run_icp_scan_job(job)
    elif job_type == "brand_report":
        await run_brand_report_job(job)
    elif job_type == "notification_dispatch":
        await run_notification_dispatch_job(job)
    elif job_type == "reopt_plan":
        await run_reopt_plan_job(job)
    elif job_type == "asana_monthly":
        await run_asana_monthly_job(job)
    elif job_type == "asana_push":
        await run_asana_push_job(job)
    elif job_type == "task_month_generate":
        await run_task_month_job(job)
    elif job_type == "task_due_sweep":
        await run_due_sweep_job(job)
    elif job_type == "task_import_asana":
        await run_task_import_job(job)
    elif job_type == "client_report":
        await run_client_report_job(job)
    elif job_type == "syndication_scan":
        await run_syndication_scan_job(job)
    elif job_type == "syndication_item":
        await run_syndication_item_job(job)
    elif job_type == "strategy_review":
        await run_strategy_review_job(job)
    elif job_type == "internal_link_analyze":
        await run_internal_link_analyze_job(job)
    elif job_type == "internal_link_apply":
        await run_internal_link_apply_job(job)
    elif job_type == "content_batch_item":
        await run_content_batch_item_job(job)
    elif job_type == "leadoff_tryout":
        await run_leadoff_tryout_job(job)
    elif job_type == "leadoff_scout":
        await run_leadoff_scout_job(job)
    elif job_type == "leadoff_ai_probe":
        await run_leadoff_ai_probe_job(job)
    elif job_type == "leadoff_permits":
        await run_leadoff_permits_job(job)
    elif job_type == "leadoff_geocode":
        await run_leadoff_geocode_job(job)
    elif job_type == "leadoff_signal_refresh":
        await run_leadoff_signal_refresh_job(job)
    elif job_type == "leadoff_income_backfill":
        await run_leadoff_income_backfill_job(job)
    elif job_type == "leadoff_county_backfill":
        await run_leadoff_county_backfill_job(job)
    elif job_type == "leadoff_city_finder":
        await run_leadoff_city_finder_job(job)
    elif job_type == "domain_overview":
        await run_domain_overview_job(job)
    elif job_type == "keyword_gap":
        await run_keyword_gap_job(job)
    elif job_type == "link_gap":
        await run_link_gap_job(job)
    elif job_type == "keyword_research":
        await run_keyword_research_job(job)
    elif job_type == "deliverables_log":
        await run_deliverables_log_job(job)
    elif job_type == "deliverable_notes_scan":
        await run_deliverable_notes_scan_job(job)
    elif job_type == "deliverables_sheet_provision":
        await run_deliverables_provision_job(job)
    elif job_type == "qa_review":
        await run_qa_review_job(job)
    elif job_type == "github_infer_patterns":
        await run_github_infer_job(job)
    elif job_type == "blog_github_publish":
        await run_blog_media_publish_job(job)
    else:
        logger.warning("job_worker.unknown_job_type", extra={"job_type": job_type})

    # Cross-module batch awareness: after a content-generation job settles (the
    # handler has already written its terminal status), check whether it was the
    # last in-flight one for its (user, client, family) group and, if so, notify
    # the user their batch finished. Best-effort — never breaks the worker.
    if job_type in activity.CONTENT_JOB_TYPES:
        try:
            activity.on_content_job_settled(job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "job_worker.activity_settle_failed",
                extra={"job_id": job.get("id"), "error": str(exc)},
            )


async def job_worker(job_types: list[str] | None = None, lane: str = "main") -> None:
    """Background loop: poll async_jobs every N seconds and process one job per tick.

    Two lanes run in-process (ops fix 2026-07-12): the MAIN lane claims
    everything (and owns the stale-job reaper), while the INTERACTIVE lane is
    restricted to short, user-awaited job types (`interactive_job_types`) so a
    just-clicked action never waits 10–20 min behind a long background job.
    The claim's status='pending' guard makes the lanes race-safe.
    """
    interval = settings.job_worker_poll_interval_seconds
    logger.info("job_worker.started", extra={"poll_interval_s": interval, "lane": lane})
    while True:
        await asyncio.sleep(interval)
        try:
            if lane == "main":
                await _reap_stale_jobs()
            job = await _claim_next_job(job_types)
            if job:
                logger.info(
                    "async_job_claimed",
                    extra={"job_id": job["id"], "job_type": job.get("job_type"), "lane": lane},
                )
                # Track as in-flight so a graceful shutdown can requeue it (see
                # `drain_inflight_jobs`). Cleared when the job settles — but NOT
                # on cancellation: shutdown cancels this task mid-job, and the id
                # must survive so the drain (which runs after the worker tasks
                # are awaited) can find and requeue it.
                _inflight_jobs.add(job["id"])
                interrupted = False
                try:
                    await _process_job(job)
                except asyncio.CancelledError:
                    interrupted = True  # leave registered for the shutdown drain
                    raise
                finally:
                    if not interrupted:
                        _inflight_jobs.discard(job["id"])
        except Exception as exc:
            logger.error("job_worker.unhandled", extra={"error": str(exc), "lane": lane})
