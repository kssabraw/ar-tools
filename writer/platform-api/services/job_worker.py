"""Async job worker — polls async_jobs table and processes website_scrape jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config import settings
from db.supabase_client import get_supabase
from services import activity
from services import content_ready
from services.brand_scan import run_brand_scan_job
from services.brand_report import run_brand_report_job
from services.brand_voice_service import run_brand_voice_scan_job
from services.icp_service import run_icp_scan_job
from services.dataforseo_rank import run_dataforseo_rank_job
from services.gbp_metrics_ingest import run_gbp_metrics_ingest_job
from services import gbp_posts_service
from services.ga4_ingest import run_ga4_ingest_job
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
from services import wheelhouse_service
from services.rank_location import run_rank_location_derive_job
from services.service_page_plan import run_service_plan_job
from services import service_page_score
from services import blog_page_score
from services.rank_analysis_report import run_rank_keyword_report_job
from services.rank_report import run_rank_report_job
from services.rank_materialize import run_gsc_materialize_job
from services.citation_check import run_citation_check_job
from services.competitor_intel import run_competitor_intel_job
from services.site_inventory import run_site_inventory_job
from services.deliverables_sheet import (
    run_log_job as run_deliverables_log_job,
    run_notes_scan_job as run_deliverable_notes_scan_job,
    run_provision_job as run_deliverables_provision_job,
)
from services.domain_intel import run_domain_overview_job, run_keyword_gap_job, run_link_gap_job
from services.github_infer import run_github_infer_job
from services.blog_media.pipeline import run_blog_media_publish_job
from services.keyword_research import run_keyword_research_job
from services.keyword_research_report import run_report_job as run_keyword_research_report_job
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
from services.backlink_explorer import run_lookup_job as run_backlink_lookup_job
from services.content_intel import run_content_intel_job
from services.leadoff_actions import (
    run_map_refresh_job as run_leadoff_map_refresh_job,
    run_scout_job as run_leadoff_scout_job,
    run_tryout_job as run_leadoff_tryout_job,
)
from services.leadoff_ai_probe import run_ai_probe_job as run_leadoff_ai_probe_job
from services.leadoff_permits import run_permits_job as run_leadoff_permits_job
from services.leadoff_geocode import run_geocode_job as run_leadoff_geocode_job
from services.leadoff_signals import run_signal_refresh_job as run_leadoff_signal_refresh_job
from services.leadoff_income import run_income_backfill_job as run_leadoff_income_backfill_job
from services.leadoff_counties import run_county_backfill_job as run_leadoff_county_backfill_job
from services.census_demand import run_placement_job as run_leadoff_placement_job
from services.leadoff_zip_demand import run_zip_demand_probe_job as run_leadoff_zip_demand_job
from services.leadoff_finder import run_city_finder_job as run_leadoff_city_finder_job
from services.local_relevance import run_local_relevance_job
from services.page_structure_scraper import analyze_page_structure
from services.silo_dedup import process_silo_dedup_job
from services.strategist import run_strategy_review_job
from services.internal_linking import run_internal_link_analyze_job, run_internal_link_apply_job
from services.syndication_service import run_syndication_item_job, run_syndication_scan_job
from services.content_batch import run_content_batch_item_job
from services.website_deploy import run_deploy_poll_job as run_website_deploy_poll_job
from services.website_generate import run_generate_job as run_website_generate_job
from services.website_provision import run_provision_job as run_website_provision_job
from services.website_publish import run_publish_job as run_website_publish_job
from services.website_theme import run_theme_compile_job as run_website_theme_compile_job
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


# How many of the oldest pending rows the claim scans past exhausted/raced rows.
_CLAIM_SCAN_LIMIT = 10


async def _claim_next_job(
    job_types: list[str] | None = None, exclude_types: list[str] | None = None
) -> dict | None:
    """Claim the oldest claimable pending job (optionally restricted to
    `job_types` — the interactive/fanout lane's filter — or with `exclude_types`
    held back for the MAIN lane, so long dedicated-lane jobs never block it) and
    atomically mark it running.

    Scans a small window of the oldest rows rather than just the single oldest:
    an exhausted (`attempts >= max_attempts`) pending row would otherwise sit at
    the queue head forever — nothing settles a *pending* row, so it freezes the
    whole lane. Such rows are failed and skipped, and a row lost to the sibling
    lane's race is stepped over instead of ending the tick empty-handed."""
    supabase = get_supabase()
    try:
        # supabase-py doesn't support FOR UPDATE SKIP LOCKED directly, so we fetch
        # the oldest pending rows and immediately mark one running.
        query = supabase.table("async_jobs").select("*").eq("status", "pending")
        if job_types:
            query = query.in_("job_type", job_types)
        if exclude_types:
            query = query.not_.in_("job_type", exclude_types)
        result = query.order("scheduled_at").limit(_CLAIM_SCAN_LIMIT).execute()
        jobs = result.data or []

        for job in jobs:
            if job.get("attempts", 0) >= job.get("max_attempts", 2):
                # Exhausted but never settled to a terminal state (e.g. a failed
                # attempt-refund during shutdown, or a manual requeue). The reaper
                # only touches 'running' rows, so this would starve the lane. Fail
                # it (guarded on pending so a real claim isn't stomped) and move on.
                failed = (
                    supabase.table("async_jobs")
                    .update({"status": "failed",
                             "error": "max_attempts_exhausted_without_settle",
                             "completed_at": "now()"})
                    .eq("id", job["id"]).eq("status", "pending").execute()
                )
                if failed.data:
                    logger.warning(
                        "job_worker.exhausted_pending_failed",
                        extra={"job_id": job["id"], "job_type": job.get("job_type"),
                               "attempts": job.get("attempts", 0)},
                    )
                continue

            # Atomic claim: the status='pending' guard means when the two in-process
            # lanes race for the same row, exactly one PATCH matches — the loser
            # gets an empty result and steps to the next candidate.
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
            if update_result.data:
                return update_result.data[0]
        return None
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


# Backoff before a re-queued transient failure becomes claimable again. The
# worker claims by oldest `scheduled_at` with no `<= now` gate, so this
# de-prioritizes the retry behind other queued work rather than hard-gating it —
# enough that a sustained nlp outage cannot hot-loop a job, without stalling the
# retry when the queue is otherwise empty. Mirrors the bulk-job staggering lever.
_TRANSIENT_RETRY_BACKOFF_MINUTES = (5, 15, 45)


def plan_job_retry(
    attempts: int, max_attempts: int, transient: bool, error: str,
    now: datetime | None = None,
) -> tuple[dict, str]:
    """Decide how a handler should settle a FAILED run: re-queue it for another
    attempt, or fail it terminally. Pure; unit-tested.

    Handlers historically wrote `status='failed'` on any exception, which made
    `max_attempts` decorative for them: the reaper only re-queues rows still in
    'running', so a handler that settles the row terminally has already opted out
    of every retry. That cost a real 8-minute ecommerce reoptimize on 2026-07-31
    — the nlp container restarted mid-stream, the SSE read died with a transport
    error, and the whole run was discarded at `attempts: 1`.

    A retry is only correct when the failure is TRANSIENT (5xx / transport — the
    classifier is `content_batch._raise_if_transient_nlp`). A 4xx is
    client-actionable and retrying cannot fix it, so it fails immediately and the
    user sees the real reason instead of the same error three attempts later.

    `attempts` is the count already consumed (the claim increments it before the
    handler runs), so `attempts >= max_attempts` means this was the last one.
    """
    if not transient or attempts >= max_attempts:
        return {"status": "failed", "error": error[:500], "completed_at": "now()"}, "failed"
    idx = min(max(attempts - 1, 0), len(_TRANSIENT_RETRY_BACKOFF_MINUTES) - 1)
    delay = _TRANSIENT_RETRY_BACKOFF_MINUTES[idx]
    when = (now or datetime.now(timezone.utc)) + timedelta(minutes=delay)
    return {
        "status": "pending",
        "started_at": None,
        "scheduled_at": when.isoformat(),
        "error": f"transient (attempt {attempts}/{max_attempts}, retrying in {delay}m): {error}"[:500],
    }, "requeued"


def settle_job_failure(job_id: str, exc: Exception, job: dict) -> None:
    """Settle a handler's failed run — re-queueing it on a transient upstream
    failure while attempts remain, else failing it terminally.

    The counterpart to the `status='failed'` line handlers write today. Uses the
    same transient classifier as the content-batch path so "retryable" means one
    thing across the suite. Best-effort: if the settle itself fails, the row stays
    'running' and the reaper picks it up, which is the correct fallback.
    """
    from services.content_batch import is_transient_upstream

    detail = str(getattr(exc, "detail", None) or exc)
    update, outcome = plan_job_retry(
        attempts=int(job.get("attempts") or 1),
        max_attempts=int(job.get("max_attempts") or 2),
        transient=is_transient_upstream(exc),
        error=detail,
    )
    try:
        get_supabase().table("async_jobs").update(update).eq("id", job_id).execute()
    except Exception:  # noqa: BLE001 — the reaper is the fallback
        logger.warning("job_worker.settle_failure_failed", extra={"job_id": job_id})
        return
    logger.warning(
        "job_worker.handler_failed",
        extra={"job_id": job_id, "job_type": job.get("job_type"),
               "outcome": outcome, "attempts": job.get("attempts"), "error": detail[:200]},
    )


def _settle_if_running(job_id: str, update: dict) -> bool:
    """Write a terminal state to a job row **only if it is still 'running'**.

    Handlers settle their own row (recording a result/error the generic path
    can't know). This is the safety net for the ones that don't: without it a
    handler that returns without settling leaves the row 'running' forever, so
    the reaper requeues it — re-running the work — and finally marks it
    `stale_timeout` even though it succeeded every time. `qa_review` did exactly
    that: 8/8 jobs "failed" while every review actually completed, and each one
    ran twice, 30 minutes apart.

    The status='running' guard is what makes this safe to call unconditionally:
    a handler that already settled has a terminal status, so this is a no-op and
    its own result/error is preserved. Best-effort — never breaks the worker."""
    try:
        result = (
            get_supabase().table("async_jobs")
            .update(update).eq("id", job_id).eq("status", "running").execute()
        )
        return bool(result.data)
    except Exception as exc:  # noqa: BLE001 — settling must never break the loop
        logger.error("job_worker.settle_failed", extra={"job_id": job_id, "error": str(exc)})
        return False


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


def _store_page_structure(client_id: str, page_type: str, entry: dict) -> None:
    """Merge `entry` into clients.page_structures[page_type] without clobbering
    the sibling page types. A read-modify-write of the JSONB column — safe
    because the worker processes one job per tick (no concurrent writers to the
    same client row). Shared by the scrape and manual-parse jobs."""
    supabase = get_supabase()
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


async def _run_page_structure_parse(job: dict) -> None:
    """Execute a page_structure_parse job: turn a client's WRITTEN page-structure
    guidelines (pasted, or parsed out of an uploaded document) into the same
    stored analysis a scrape produces.

    Used when there's no live page to scrape — a client with no website yet, or
    one whose layout is specified in a brand/design document rather than shipped
    on a site. The guidelines text rides the job payload so the parse re-runs
    against exactly what was submitted."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    page_type = payload.get("page_type")
    guidelines = payload.get("guidelines_text") or ""
    original_filename = payload.get("original_filename")
    job_id = job["id"]

    logger.info(
        "page_structure_parse_started",
        extra={
            "job_id": job_id,
            "client_id": client_id,
            "page_type": page_type,
            "chars": len(guidelines),
        },
    )

    supabase = get_supabase()
    try:
        from services.page_structure_manual import parse_guidelines

        analysis = await parse_guidelines(guidelines, page_type)
        _store_page_structure(
            client_id,
            page_type,
            {
                # No URL for a manual reference; `source` is what tells the UI
                # (and a future re-analysis) which capture path owns this entry.
                "url": "",
                "source": "manual",
                "guidelines_text": guidelines,
                "original_filename": original_filename,
                "status": "complete",
                "error": None,
                "empty": False,
                "note": None,
                "analysis": analysis,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": analysis, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info(
            "page_structure_parse_complete",
            extra={
                "job_id": job_id,
                "client_id": client_id,
                "page_type": page_type,
                "sections": len(analysis.get("outline") or []),
            },
        )
    except Exception as exc:
        logger.warning(
            "page_structure_parse_failed",
            extra={
                "job_id": job_id,
                "client_id": client_id,
                "page_type": page_type,
                "error": str(exc),
            },
        )
        try:
            # Keep the submitted text on the entry so the user can see + fix what
            # failed to parse instead of having to retype it.
            _store_page_structure(
                client_id,
                page_type,
                {
                    "url": "",
                    "source": "manual",
                    "guidelines_text": guidelines,
                    "original_filename": original_filename,
                    "status": "failed",
                    "error": str(exc)[:500],
                },
            )
        except Exception:
            logger.error("page_structure_parse_store_failed", extra={"job_id": job_id})
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
    supabase = get_supabase()

    logger.info(
        "page_structure_scrape_started",
        extra={"job_id": job_id, "client_id": client_id, "page_type": page_type, "url": url},
    )

    def _store(entry: dict) -> None:
        _store_page_structure(client_id, page_type, entry)

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
                "source": "scrape",
                # A page type can be switched from manual guidelines to a scraped
                # URL; clear the manual payload so the entry has one source.
                "guidelines_text": None,
                "original_filename": None,
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
            _store({"url": url, "source": "scrape", "status": "failed", "error": str(exc)[:500]})
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
    elif job_type == "site_inventory":
        await run_site_inventory_job(job)
    elif job_type == "page_backlink_intel":
        await run_page_backlink_job(job)
    elif job_type == "website_scrape":
        await _run_website_scrape(job)
    elif job_type == "website_provision":
        await run_website_provision_job(job.get("payload") or {})
    elif job_type == "website_page_generate":
        await run_website_generate_job(job)
    elif job_type == "website_page_publish":
        await run_website_publish_job(job)
    elif job_type == "website_deploy_poll":
        await run_website_deploy_poll_job(job)
    elif job_type == "website_theme_compile":
        await run_website_theme_compile_job(job)
    elif job_type == "page_structure_scrape":
        await _run_page_structure_scrape(job)
    elif job_type == "page_structure_parse":
        await _run_page_structure_parse(job)
    elif job_type == "silo_dedup":
        await process_silo_dedup_job(job)
    elif job_type == "gsc_ingest":
        await run_gsc_ingest_job(job)
    elif job_type == "gsc_page_ingest":
        await run_gsc_page_ingest_job(job)
    elif job_type == "ga4_ingest":
        await run_ga4_ingest_job(job)
    elif job_type == "gbp_metrics_ingest":
        await run_gbp_metrics_ingest_job(job)
    elif job_type == "gbp_onboard":
        from services import gbp_locations_service
        await gbp_locations_service.run_gbp_onboard_job(job)
    elif job_type == "gbp_search_keywords":
        from services import gbp_search_keywords
        await gbp_search_keywords.run_gbp_search_keywords_job(job)
    elif job_type == "gbp_reviews":
        from services import gbp_reviews_ingest
        await gbp_reviews_ingest.run_gbp_reviews_job(job)
    elif job_type == "gbp_post_publish":
        await gbp_posts_service.run_publish_job(job)
    elif job_type == "gbp_post_generate":
        await gbp_posts_service.run_generate_job(job)
    elif job_type == "gbp_posts_sync":
        await gbp_posts_service.run_sync_job(job)
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
    elif job_type == "backlink_lookup":
        await run_backlink_lookup_job(job)
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
    elif job_type == "wheelhouse_generate":
        await wheelhouse_service.run_generate_job(job)
    elif job_type == "service_page_plan":
        await run_service_plan_job(job)
    elif job_type == "service_page_score":
        await service_page_score.run_score_job(job)
    elif job_type == "service_page_reoptimize":
        await service_page_score.run_reoptimize_job(job)
    elif job_type == "score_external":
        from services import score_external

        await score_external.run_job(job)
    elif job_type == "blog_score":
        await blog_page_score.run_score_job(job)
    elif job_type == "blog_reoptimize":
        await blog_page_score.run_reoptimize_job(job)
    elif job_type == "fanout_blog_score":
        from fanout import reoptimize as fanout_reoptimize

        await fanout_reoptimize.run_score_job(job)
    elif job_type == "fanout_blog_reoptimize":
        from fanout import reoptimize as fanout_reoptimize

        await fanout_reoptimize.run_reoptimize_job(job)
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
    elif job_type == "everhour_mirror":
        from services import everhour_sync

        await everhour_sync.run_mirror_job(job)
    elif job_type == "everhour_sync":
        from services import everhour_sync

        await everhour_sync.run_everhour_sync_job(job)
    elif job_type == "client_report":
        await run_client_report_job(job)
    elif job_type == "syndication_scan":
        await run_syndication_scan_job(job)
    elif job_type == "syndication_item":
        await run_syndication_item_job(job)
    elif job_type == "strategy_review":
        await run_strategy_review_job(job)
    elif job_type == "autonomy_run":
        from services.autonomy_executor import run_autonomy_job
        await run_autonomy_job(job)
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
    elif job_type == "leadoff_map_refresh":
        await run_leadoff_map_refresh_job(job)
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
    elif job_type == "leadoff_placement":
        await run_leadoff_placement_job(job)
    elif job_type == "leadoff_zip_demand":
        await run_leadoff_zip_demand_job(job)
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
    elif job_type == "keyword_research_report":
        await run_keyword_research_report_job(job)
    elif job_type == "keyword_topic_research":
        from services.keyword_topic_research import run_topic_research_job
        await run_topic_research_job(job)
    elif job_type == "fanout_report":
        from fanout.report_runner import run_report_job as run_fanout_report_job
        await run_fanout_report_job(job)
    elif job_type in (
        "fanout_expand", "fanout_plan", "fanout_regate", "fanout_fanout",
        "fanout_architecture",
    ):
        # Durable Fanout pipeline stages (issue #686). Each runs the blocking
        # pipeline in a thread so it doesn't stall this (dedicated) lane's event
        # loop; the row settles complete after it returns, or stays running for
        # the drain/reaper to requeue on a crash. The payload carries the stage's
        # params (mirrors the old submit_* signatures).
        import fanout.jobs as _fjobs
        payload = job.get("payload") or {}
        session_id = payload.get("session_id") or job.get("entity_id")
        if job_type == "fanout_expand":
            await asyncio.to_thread(_fjobs.run_expand_durable, session_id)
        elif job_type == "fanout_plan":
            await asyncio.to_thread(
                _fjobs.run_plan_durable, session_id, bool(payload.get("direct"))
            )
        elif job_type == "fanout_regate":
            await asyncio.to_thread(
                _fjobs.run_regate_durable, session_id,
                payload.get("threshold"), payload.get("edge_threshold"),
                payload.get("resolution"), payload.get("active_per_silo_cap"),
                payload.get("seed_terms") or [], payload.get("peer_terms") or [],
                payload.get("silo_margin"),
            )
        elif job_type == "fanout_fanout":
            await asyncio.to_thread(
                _fjobs.run_fanout_durable, session_id,
                payload.get("threshold"), payload.get("edge_threshold"),
                payload.get("resolution"), payload.get("active_per_silo_cap"),
                payload.get("seed_terms") or [], payload.get("peer_terms") or [],
            )
        else:  # fanout_architecture
            await asyncio.to_thread(_fjobs.run_architecture_durable, session_id)
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
    elif job_type == "illustrate_run":
        from services.illustration import run_illustrate_job

        await run_illustrate_job(job)
    elif job_type == "blog_github_publish":
        await run_blog_media_publish_job(job)
    elif job_type == "voice_revalidate":
        from services import voice_revalidate
        await voice_revalidate.run_revalidate_job(job)
    else:
        logger.warning("job_worker.unknown_job_type", extra={"job_type": job_type})
        # Settle as failed, not complete: an unroutable job type is a real
        # defect (a producer enqueueing a type the worker can't handle) and
        # must not be masked by the success safety net below.
        _settle_if_running(
            job["id"],
            {"status": "failed", "error": f"unknown_job_type: {job_type}",
             "completed_at": "now()"},
        )
        return

    # Safety net: the handler returned without raising, so the job is done. If it
    # settled its own row this is a no-op (guarded on status='running'); if it
    # forgot, this is what keeps the row from being reaped and re-run.
    if _settle_if_running(job["id"], {"status": "complete", "completed_at": "now()"}):
        logger.info("job_worker.settled_by_worker",
                    extra={"job_id": job["id"], "job_type": job_type})

    # Cross-module activity awareness: after a settled job that a user started and
    # may have navigated away from, tell them it's done. Content page jobs roll up
    # into one per-batch notification; single registered jobs get one per-job
    # completion ping (both to the initiator's header bell). Every path is gated
    # on payload.user_id, so scheduled/background runs never ping. Best-effort.
    if job_type in activity.ACTIVITY_JOB_TYPES:
        try:
            activity.on_job_settled(job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "job_worker.activity_settle_failed",
                extra={"job_id": job.get("id"), "error": str(exc)},
            )

    # Client-facing "content ready" Slack ping (PACE, services/content_ready.py):
    # after the LAST in-flight job of a client's content-creation batch settles,
    # post one summary message to that client's own Slack channel. Unlike the
    # activity ping above this is not gated on payload.user_id — a scheduled
    # background generation should tell the client's channel too. Best-effort.
    if job_type in content_ready.JOB_TYPES:
        try:
            content_ready.on_job_settled(job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "job_worker.content_ready_settle_failed",
                extra={"job_id": job.get("id"), "error": str(exc)},
            )


async def job_worker(
    job_types: list[str] | None = None,
    lane: str = "main",
    exclude_types: list[str] | None = None,
) -> None:
    """Background loop: poll async_jobs every N seconds and process one job per tick.

    Lanes run in-process (ops fix 2026-07-12): the MAIN lane claims everything
    (and owns the stale-job reaper) EXCEPT `exclude_types` — the long, blocking
    Fanout pipeline jobs, which get their own dedicated lane so a ~10-min run
    can't stall the reaper or other background work (issue #686). The INTERACTIVE
    lane is restricted to short, user-awaited job types (`interactive_job_types`)
    so a just-clicked action never waits behind a long background job.
    The claim's status='pending' guard makes the lanes race-safe.
    """
    interval = settings.job_worker_poll_interval_seconds
    logger.info("job_worker.started", extra={"poll_interval_s": interval, "lane": lane})
    while True:
        await asyncio.sleep(interval)
        try:
            if lane == "main":
                await _reap_stale_jobs()
            job = await _claim_next_job(job_types, exclude_types)
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
