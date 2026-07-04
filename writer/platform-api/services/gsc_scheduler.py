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
    """Daily: enqueue a DataForSEO rank job for each client whose per-client
    fetch schedule is due today.

    Each client with active keywords has an optional rank_fetch_config row
    (mode off/weekly/monthly/interval). A client with no row defaults to the
    legacy cadence — weekly on the global `dataforseo_rank_weekday` — so existing
    clients are unchanged. The job itself skips keywords GSC already covers, so
    this is cheap for GSC-connected clients and the sole rank source otherwise.
    """
    from datetime import datetime, timezone

    from services.dataforseo_rank import enqueue_dataforseo_rank, is_fetch_due

    supabase = get_supabase()
    rows = (
        supabase.table("tracked_keywords")
        .select("client_id")
        .eq("active", True)
        .execute()
    )
    client_ids = {r["client_id"] for r in (rows.data or [])}
    if not client_ids:
        return 0

    # Only schedule clients with a website — DataForSEO finds the rank by matching
    # the client's domain in the SERP, so a websiteless client can never produce
    # one. Skipping them here (rather than enqueuing a job that always fails)
    # avoids daily re-enqueue churn for interval schedules and keeps
    # last_fetched_at meaning "last real pull". Once a website is added the next
    # tick picks the client up immediately.
    client_rows = (
        supabase.table("clients").select("id, website_url")
        .in_("id", list(client_ids)).execute()
    ).data or []
    fetchable = {c["id"] for c in client_rows if (c.get("website_url") or "").strip()}

    configs = (
        supabase.table("rank_fetch_config").select("*")
        .in_("client_id", list(client_ids)).execute()
    ).data or []
    config_by_client = {c["client_id"]: c for c in configs}

    today = datetime.now(timezone.utc).date()
    default_weekday = settings.dataforseo_rank_weekday
    due = 0
    for client_id in client_ids & fetchable:
        cfg = config_by_client.get(client_id, {})
        if is_fetch_due(cfg, today, default_weekday):
            enqueue_dataforseo_rank(client_id)
            due += 1
    if due:
        logger.info("gsc_scheduler.dataforseo_enqueued", extra={"clients": due})
    return due


def enqueue_due_syndication_scans() -> int:
    """Daily: enqueue a syndication_scan job for each client whose Content
    Syndication is enabled and due (last_scan_date older than its interval_days).

    `last_scan_date` is advanced by the scan job on success (not here), so a scan
    that fails re-runs next cycle rather than being skipped. enqueue_scan dedupes
    against an in-flight scan, so re-evaluating a still-pending client is a no-op.
    A websiteless client is skipped (the scan would find nothing)."""
    from datetime import datetime, timezone

    from services.syndication_service import enqueue_scan

    supabase = get_supabase()
    configs = (
        supabase.table("syndication_config").select("*").eq("enabled", True).execute()
    ).data or []
    if not configs:
        return 0

    client_ids = [c["client_id"] for c in configs]
    client_rows = (
        supabase.table("clients").select("id, website_url").in_("id", client_ids).execute()
    ).data or []
    websites = {c["id"]: (c.get("website_url") or "").strip() for c in client_rows}

    today = datetime.now(timezone.utc).date()
    due = 0
    for cfg in configs:
        client_id = cfg["client_id"]
        if not websites.get(client_id):
            continue
        interval = max(1, int(cfg.get("interval_days") or 1))
        last = cfg.get("last_scan_date")
        last_date = date.fromisoformat(last) if isinstance(last, str) else last
        if last_date is not None and (today - last_date).days < interval:
            continue
        if enqueue_scan(client_id):
            due += 1
    if due:
        logger.info("gsc_scheduler.syndication_enqueued", extra={"clients": due})
    return due


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


def enqueue_due_gsc_research() -> int:
    """First-entry + monthly: enqueue a GSC Research run (cannibalization / quick
    wins / hidden wins) for each GSC-eligible client that has never had one, or
    whose last completed run is at least `gsc_research_interval_days` old.

    Gated on GSC actually being provisioned (service account + a verified
    property) — GSC Research can't produce anything otherwise. On-demand runs are
    unaffected. enqueue_gsc_research dedupes against any in-flight run.
    """
    from datetime import date

    from services.gsc_research import enqueue_gsc_research, is_gsc_research_due

    if not (settings.gsc_research_auto_enabled and settings.google_service_account_key):
        return 0
    supabase = get_supabase()
    props = (
        supabase.table("gsc_properties").select("client_id").eq("access_status", "ok").execute()
    ).data or []
    client_ids = sorted({p["client_id"] for p in props})
    if not client_ids:
        return 0
    runs = (
        supabase.table("gsc_research_runs")
        .select("client_id, created_at")
        .eq("status", "complete")
        .in_("client_id", client_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    last_by: dict[str, date] = {}
    for r in runs:  # newest-first → first seen per client wins
        cid = r["client_id"]
        if cid not in last_by and r.get("created_at"):
            last_by[cid] = date.fromisoformat(r["created_at"][:10])
    today = date.today()
    due = 0
    for cid in client_ids:
        if is_gsc_research_due(last_by.get(cid), today, settings.gsc_research_interval_days):
            enqueue_gsc_research(cid, trigger="scheduled")
            due += 1
    if due:
        logger.info("gsc_scheduler.gsc_research_enqueued", extra={"clients": due})
    return due


def enqueue_due_reopt_plans() -> int:
    """Weekly: enqueue a reopt_plan job per client with active keywords — the
    routine action-plan digest. The job builds the plan from already-produced
    signals (open drops, rankability, GSC-Research) and notifies only when it
    finds something. enqueue_reopt_plan dedupes against any in-flight one."""
    from services.reopt_planner import enqueue_reopt_plan

    if not settings.reopt_plan_auto_enabled:
        return 0
    supabase = get_supabase()
    rows = supabase.table("tracked_keywords").select("client_id").eq("active", True).execute()
    client_ids = {r["client_id"] for r in (rows.data or [])}
    for client_id in client_ids:
        enqueue_reopt_plan(client_id, trigger="scheduled")
    if client_ids:
        logger.info("gsc_scheduler.reopt_plans_enqueued", extra={"clients": len(client_ids)})
    return len(client_ids)


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
    """Background loop: daily GSC ingest enqueue + per-client-scheduled DataForSEO
    rank enqueue (evaluated daily) + weekly Maps geo-grid scans, and a per-tick
    poll of in-flight Maps scans."""
    from services.asana_monthly import enqueue_due_asana_monthly
    from services.asana_service import shift_months
    from services.asana_workload import run_workload_alert
    from services.brand_schedule import enqueue_due_brand_scans
    from services.freeze import enqueue_due_freeze_checks
    from services.local_dominator import enqueue_due_maps_scans, poll_pending_maps_scans
    from services.offpage_agent import run_offpage_sweep
    from services.response_episodes import run_episode_sync

    interval = settings.gsc_scheduler_poll_interval_seconds
    hour = settings.gsc_ingest_hour_utc
    weekday = settings.dataforseo_rank_weekday
    maps_weekday = settings.maps_scan_weekday
    reopt_weekday = settings.reopt_plan_weekday
    last_run_date: Optional[date] = None
    last_df_date: Optional[date] = None
    last_maps_date: Optional[date] = None
    last_reopt_date: Optional[date] = None
    last_asana_month: Optional[tuple] = None
    last_asana_workload_date: Optional[date] = None
    logger.info("gsc_scheduler.started", extra={"poll_interval_s": interval, "hour_utc": hour})
    while True:
        await asyncio.sleep(interval)
        try:
            now = datetime.now(timezone.utc)
            if should_run(now, last_run_date, hour):
                enqueue_due_ingests()
                enqueue_due_market()
                enqueue_due_reports()
                enqueue_due_gsc_research()
                # DataForSEO rank pull is now per-client scheduled (weekly/
                # monthly/interval/off); the enqueue helper decides who is due
                # today, so it runs daily rather than on one global weekday.
                enqueue_due_dataforseo()
                # Daily Content Syndication scan (per-client interval-gated).
                enqueue_due_syndication_scans()
                # Daily Freeze Protocol check (homepage deindex detection).
                enqueue_due_freeze_checks()
                # Daily response-episode sync (the SOPs' 2-week/6-week verify loop).
                run_episode_sync()
                # Daily offpage sweep (RD loss / unnatural spike — SOP §A.5).
                run_offpage_sweep()
                last_run_date = now.date()
            # Weekly query×page ingest + competitive SERP snapshots still
            # piggyback the global DataForSEO weekday (diagnostic/GSC-side data,
            # not the per-client tracked rank).
            if now.weekday() == weekday and should_run(now, last_df_date, hour):
                enqueue_due_page_ingest()
                # SERP snapshots are now captured on keyword first-entry, on a
                # detected rank drop (≤1/mo), and on-demand — not weekly — unless
                # serp_snapshot_auto_weekly is re-enabled (cost vs trend density).
                if settings.serp_snapshot_auto_weekly:
                    enqueue_due_serp_snapshots()
                last_df_date = now.date()
            # Weekly Maps geo-grid scans (Module #5) on their own weekday.
            if now.weekday() == maps_weekday and should_run(now, last_maps_date, hour):
                enqueue_due_maps_scans()
                last_maps_date = now.date()
            # Weekly reoptimization action-plan digest on its own weekday.
            if now.weekday() == reopt_weekday and should_run(now, last_reopt_date, hour):
                enqueue_due_reopt_plans()
                last_reopt_date = now.date()
            # Monthly Asana section automation: once per month on the configured
            # day-of-month, enqueue an asana_monthly job per mapped client (the
            # job itself no-ops if the month's section already exists).
            if (
                now.day >= settings.asana_month_generate_day
                and last_asana_month != (now.year, now.month)
                and now.hour >= hour
            ):
                target = shift_months(now.date(), settings.asana_month_target_offset)
                enqueue_due_asana_monthly(target)
                last_asana_month = (now.year, now.month)
            # Daily Team Workload overload alert (effort-weighted): once per day
            # after the target hour, emit one suite notification if anyone is
            # over capacity. run_workload_alert self-guards when unconfigured.
            if should_run(now, last_asana_workload_date, hour):
                await run_workload_alert()
                last_asana_workload_date = now.date()
            # Advance any in-flight Maps scans every tick (non-blocking GETs).
            await poll_pending_maps_scans()
            # AI Visibility scheduled scans are self-clocked via each schedule's
            # next_run_at, so they're evaluated every tick (cheap due-query).
            enqueue_due_brand_scans()
        except Exception as exc:
            logger.error("gsc_scheduler.unhandled", extra={"error": str(exc)})
