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


# ---------------------------------------------------------------------------
# Durable run markers (ops fix 2026-07-12)
#
# The loop's "already ran today/this week" markers were in-memory only, so
# every deploy restarted the process and re-fired the daily block —
# freeze_check ran up to 17×/client/day on heavy deploy days, burning GSC
# URL-inspection quota + paid DataForSEO site: probes. Markers now load from
# the `scheduler_state` table at loop start and persist after each block runs.
# Best-effort on both sides: an unreadable table degrades to the old
# in-memory behavior (markers start None), and a failed save just means the
# marker is re-derived next deploy — never a crashed scheduler.
# ---------------------------------------------------------------------------
def parse_marker_date(value) -> Optional[date]:
    """'YYYY-MM-DD' → date; None on missing/garbage. Pure."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def parse_marker_month(value) -> Optional[tuple]:
    """'YYYY-MM' → (year, month); None on missing/garbage. Pure."""
    if not value:
        return None
    try:
        y, m = str(value).split("-")[:2]
        return (int(y), int(m))
    except (ValueError, TypeError):
        return None


def load_scheduler_state() -> dict:
    """All persisted markers as {key: value}. Best-effort — {} on any error."""
    try:
        rows = (
            get_supabase().table("scheduler_state").select("key, value").execute()
        ).data or []
        return {r["key"]: r["value"] for r in rows if r.get("key")}
    except Exception as exc:
        logger.warning("gsc_scheduler.state_load_failed", extra={"error": str(exc)})
        return {}


def save_marker(key: str, value: str) -> None:
    """Persist one marker. Best-effort — a failure never breaks the loop."""
    try:
        get_supabase().table("scheduler_state").upsert(
            {"key": key, "value": value, "updated_at": "now()"}, on_conflict="key"
        ).execute()
    except Exception as exc:
        logger.warning(
            "gsc_scheduler.state_save_failed", extra={"key": key, "error": str(exc)}
        )


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


def enqueue_due_gbp_metrics() -> int:
    """Daily: enqueue a gbp_metrics_ingest job for each verified GBP location.

    Gated on ``gbp_metrics_enabled`` (dormant until Google approves Business
    Profile API quota + the service account is a Manager on each profile). The
    ingest re-pulls a trailing window, so a missed run self-heals; dedupes
    against any in-flight job for the same location."""
    if not settings.gbp_metrics_enabled:
        return 0
    supabase = get_supabase()
    locs = (
        supabase.table("gbp_locations").select("id").eq("access_status", "ok").execute()
    )
    enqueued = 0
    for loc in locs.data or []:
        location_row_id = loc["id"]
        existing = (
            supabase.table("async_jobs")
            .select("id")
            .eq("job_type", "gbp_metrics_ingest")
            .eq("entity_id", location_row_id)
            .in_("status", ["pending", "running"])
            .limit(1)
            .execute()
        )
        if existing.data:
            continue
        supabase.table("async_jobs").insert(
            {
                "job_type": "gbp_metrics_ingest",
                "entity_id": location_row_id,
                "payload": {"location_row_id": location_row_id},
            }
        ).execute()
        enqueued += 1
    if enqueued:
        logger.info("gsc_scheduler.gbp_metrics_enqueued", extra={"jobs": enqueued})
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


def enqueue_due_keyword_reports() -> int:
    """Weekly: enqueue an Organic Rank Analysis report per active keyword that has
    a SERP snapshot to analyze (runs the day after the weekly snapshot pass so the
    landscape is fresh). Gated on rank_analysis_auto_enabled; a keyword with no
    snapshot is skipped (its competitive half needs one). Deduped by the
    pending-row guard in enqueue_rank_keyword_report."""
    if not settings.rank_analysis_auto_enabled:
        return 0
    from services.rank_analysis_report import enqueue_rank_keyword_report

    supabase = get_supabase()
    kws = (
        supabase.table("tracked_keywords").select("id, keyword, client_id")
        .eq("active", True).execute()
    ).data or []
    if not kws:
        return 0
    kw_ids = [k["id"] for k in kws]
    with_snap: set[str] = set()
    for i in range(0, len(kw_ids), 200):
        chunk = kw_ids[i:i + 200]
        with_snap.update(
            r["keyword_id"] for r in (
                supabase.table("serp_snapshots").select("keyword_id")
                .in_("keyword_id", chunk)
                .in_("status", ["complete", "partial"]).execute()
            ).data or []
        )
    count = 0
    for k in kws:
        if k["id"] in with_snap:
            if enqueue_rank_keyword_report(k["client_id"], k["id"], k["keyword"], trigger="weekly"):
                count += 1
    if count:
        logger.info("gsc_scheduler.keyword_reports_enqueued", extra={"reports": count})
    return count


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
    from services.task_monthly import enqueue_due_task_months
    from services.task_workload import enqueue_due_sweep
    from services.task_workload import run_workload_alert as run_native_workload_alert
    from services.pace_digest import run_daily_digest as run_pace_digest
    from services.brand_schedule import enqueue_due_brand_scans
    from services.gbp_posts_service import (
        enqueue_due_gbp_post_schedules,
        enqueue_due_gbp_post_syncs,
        enqueue_due_gbp_scheduled_posts,
    )
    from services.client_report_schedule import enqueue_due_report_schedules
    from services.content_batch import enqueue_due_content_items
    from services.freeze import enqueue_due_freeze_checks
    from services.local_dominator import enqueue_due_maps_scans, poll_pending_maps_scans
    from services.citation_check import enqueue_due_citation_checks
    from services.competitor_intel import enqueue_due_competitor_intel
    from services.deliverables_sheet import enqueue_due_notes_scans as enqueue_due_deliverable_notes
    from services.domain_intel import enqueue_due_domain_intel
    from services.trend_watch import run_trend_sweep
    from services.offpage_agent import run_offpage_sweep
    from services.leadoff_calibration import (
        run_calibration_sweep as run_leadoff_calibration_sweep,
    )
    from services.leadoff_permits import enqueue_due_permits as enqueue_due_leadoff_permits
    from services.leadoff_signals import enqueue_due_signal_refresh as enqueue_due_leadoff_signals
    from services.leadoff_income import enqueue_due_income_backfill as enqueue_due_leadoff_income
    from services.leadoff_counties import enqueue_due_county_backfill as enqueue_due_leadoff_counties
    from services.page_backlink_intel import enqueue_due_page_backlinks
    from services.backlink_explorer import auto_track_client_domains, enqueue_due_backlink_snapshots
    from services.response_episodes import run_episode_sync
    from services.orchestrator import redispatch_due_retries

    from services.strategist import enqueue_due_strategy_reviews

    interval = settings.gsc_scheduler_poll_interval_seconds
    hour = settings.gsc_ingest_hour_utc
    weekday = settings.dataforseo_rank_weekday
    maps_weekday = settings.maps_scan_weekday
    reopt_weekday = settings.reopt_plan_weekday
    rank_analysis_weekday = settings.rank_analysis_weekly_weekday
    # Durable markers: survive deploys so the daily/weekly blocks don't re-fire
    # on every restart (see the ops-fix comment above).
    state = load_scheduler_state()
    last_run_date = parse_marker_date(state.get("daily"))
    last_df_date = parse_marker_date(state.get("df_weekly"))
    last_maps_date = parse_marker_date(state.get("maps_weekly"))
    last_reopt_date = parse_marker_date(state.get("reopt_weekly"))
    last_strategist_date = parse_marker_date(state.get("strategist_daily"))
    last_rank_analysis_date = parse_marker_date(state.get("rank_analysis_weekly"))
    last_asana_month = parse_marker_month(state.get("asana_month"))
    last_asana_workload_date = parse_marker_date(state.get("workload_daily"))
    logger.info(
        "gsc_scheduler.started",
        extra={"poll_interval_s": interval, "hour_utc": hour,
               "restored_markers": sum(1 for v in state.values() if v)},
    )
    while True:
        await asyncio.sleep(interval)
        try:
            now = datetime.now(timezone.utc)
            if should_run(now, last_run_date, hour):
                enqueue_due_ingests()
                # Daily GBP performance-metrics ingest (no-op until enabled).
                enqueue_due_gbp_metrics()
                # GBP Posts — daily live-state reconciliation (catches async
                # REJECTED + imports external posts). The recurring-draft tick +
                # one-off scheduled publishes are evaluated PER-CYCLE below so
                # they fire near their local time, not once a day.
                enqueue_due_gbp_post_syncs()
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
                # LeadOff calibration outcome checks (Phase 0 — read-only,
                # $0; at most one check per prediction per ~28 days).
                run_leadoff_calibration_sweep()
                # BPS prospect-pipeline refresh (free flat files; the job
                # only actually runs when the store is empty or stale).
                enqueue_due_leadoff_permits()
                # LeadOff household-income backfill (free Census ACS; the job
                # only runs when the store is empty or ~annually stale). Feeds
                # the peer-cohort field-strength signal.
                enqueue_due_leadoff_income()
                # LeadOff per-city county backfill (free Census reverse-geocode;
                # runs once to fill, then only tops up new cities). Powers the
                # board's county filter.
                enqueue_due_leadoff_counties()
                # LeadOff market-signal cache refresh ($0 — proximity +
                # footprint + peer-cohort precompute for the board grade;
                # self-gates on empty/stale cache).
                enqueue_due_leadoff_signals()
                # Weekly citation liveness (per-client interval-gated) +
                # monthly page-level RD-imbalance captures.
                enqueue_due_citation_checks()
                enqueue_due_competitor_intel()
                # Weekly Domain Intelligence keyword-gap refresh (per-client
                # interval-gated; notifies on newly-opened gaps).
                enqueue_due_domain_intel()
                run_trend_sweep()
                enqueue_due_page_backlinks()
                # Auto-track each client's own domain (idempotent), then run the
                # tracked-target backlink re-snapshots (interval-gated per target;
                # the paid pull draws from the daily backlink budget).
                auto_track_client_domains()
                enqueue_due_backlink_snapshots()
                # Daily native-task due sweep (due-today/overdue digest).
                # Self-gated: no-ops while native_tasks_enabled is false.
                enqueue_due_sweep()
                # Daily PACE delivery digest (deterministic; atomic dedupe_key).
                # Self-gated: no-ops while pace_enabled is false.
                run_pace_digest()
                # Weekly PACE delivery report (portfolio) — self-gated on
                # pace_enabled + a configured pace_report_weekday (off by default).
                from services.pace_report import maybe_emit_weekly as run_pace_report
                run_pace_report(now.date())
                # Daily PACE follow-through episode sync (v1.4 §4.9) — open/
                # resolve/clock/escalate — then the Chase Plan built from it.
                # Both self-gated on pace_enabled + pace_initiative_enabled;
                # the plan's notification dedupe_key makes it once-per-day
                # across restarts. (Importing pace_episodes also registers its
                # chase generator with the proposal engine.)
                from services import pace_rebalance, pace_slips, pace_triage  # noqa: F401 — register generators
                from services.pace_episodes import run_episode_sync as run_pace_episode_sync
                from services.pace_proposals import run_daily_chase_plan
                run_pace_episode_sync(now.date())
                await run_daily_chase_plan(now.date())
                # Per-person morning DM briefs (§4.13) — additionally gated on
                # pace_daily_brief_push (off until the im:write scope lands).
                from services.pace_briefs import run_morning_briefs
                await run_morning_briefs(now.date())
                # Weekly Pulse — the copy-paste client update block on each
                # workspace (staff-delivered; self-gated on pulse_weekday +
                # pulse_enabled; idempotent upsert + 2-week retention purge).
                # Threaded: the narrative pass makes one small sync LLM call
                # per client, which must not block the scheduler's event loop.
                from services.client_pulse import run_weekly_pulses
                await asyncio.to_thread(run_weekly_pulses, now.date())
                last_run_date = now.date()
                save_marker("daily", last_run_date.isoformat())
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
                save_marker("df_weekly", last_df_date.isoformat())
            # Weekly Maps geo-grid scans (Module #5) on their own weekday.
            if now.weekday() == maps_weekday and should_run(now, last_maps_date, hour):
                enqueue_due_maps_scans()
                last_maps_date = now.date()
                save_marker("maps_weekly", last_maps_date.isoformat())
            # Weekly reoptimization action-plan digest on its own weekday.
            if now.weekday() == reopt_weekday and should_run(now, last_reopt_date, hour):
                enqueue_due_reopt_plans()
                last_reopt_date = now.date()
                save_marker("reopt_weekly", last_reopt_date.isoformat())
            # SerMaStr strategist reviews — now per-client staggered: each
            # client has its own review weekday (clients.strategist_weekday,
            # unset → the global default), so the due-check runs DAILY and the
            # enqueue helper filters to the clients whose day is today. The
            # durable weekly guard keeps each client to one scheduled run/week;
            # the helper no-ops entirely while strategist_enabled is false.
            if should_run(now, last_strategist_date, hour):
                enqueue_due_strategy_reviews(now.weekday())
                last_strategist_date = now.date()
                save_marker("strategist_daily", last_strategist_date.isoformat())
            # Weekly Organic Rank Analysis reports (per keyword with a snapshot),
            # the day after the weekly SERP-snapshot pass. No-ops entirely while
            # rank_analysis_auto_enabled is false.
            if now.weekday() == rank_analysis_weekday and should_run(now, last_rank_analysis_date, hour):
                enqueue_due_keyword_reports()
                last_rank_analysis_date = now.date()
                save_marker("rank_analysis_weekly", last_rank_analysis_date.isoformat())
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
                # Native monthly generation rides the same cadence (self-gated
                # on native_tasks_enabled; per-task idempotent).
                enqueue_due_task_months(target)
                last_asana_month = (now.year, now.month)
                save_marker("asana_month", f"{now.year:04d}-{now.month:02d}")
            # Daily Team Workload overload alert (effort-weighted): once per day
            # after the target hour, emit one suite notification if anyone is
            # over capacity. run_workload_alert self-guards when unconfigured.
            if should_run(now, last_asana_workload_date, hour):
                # Overload math is identical; the data source follows the
                # parallel-run flag (native tasks vs Asana fetches).
                if settings.native_tasks_enabled:
                    await run_native_workload_alert()
                else:
                    await run_workload_alert()
                last_asana_workload_date = now.date()
                save_marker("workload_daily", last_asana_workload_date.isoformat())
            # Advance any in-flight Maps scans every tick (non-blocking GETs).
            await poll_pending_maps_scans()
            # AI Visibility scheduled scans are self-clocked via each schedule's
            # next_run_at, so they're evaluated every tick (cheap due-query).
            enqueue_due_brand_scans()
            # GBP Posts — recurring drafts (self-clocked next_run_at) + one-off
            # scheduled publishes (per-post scheduled_at). Evaluated every tick so
            # they fire near their local time. No-op until the module is enabled.
            enqueue_due_gbp_post_schedules()
            enqueue_due_gbp_scheduled_posts()
            # Client Reporting scheduled reports (Phase 5) — same self-clocked
            # next_run_at pattern; delivery runs after each scheduled render.
            enqueue_due_report_schedules()
            # Content Scheduler: release any scheduled bulk-page items that have
            # come due (per-item scheduled_at; evaluated every tick so drip/weekly
            # slots fire near their local time-of-day).
            enqueue_due_content_items()
            # Resilience: re-dispatch runs parked in `retry_scheduled` whose
            # transient-failure backoff has elapsed (per-run next_retry_at). Runs
            # every tick so a recovered upstream (e.g. DataForSEO) picks the run
            # back up within one poll interval of its due time.
            await redispatch_due_retries()
            # Deliverables Sheet Sync — the client-Notes poller (~15-min per-
            # client interval, self-gated via deliverables_notes_state.scanned_at
            # + in-flight job guard; no-ops while deliverables_sheet_enabled is
            # false or no client has a sheet configured).
            enqueue_due_deliverable_notes()
        except Exception as exc:
            logger.error("gsc_scheduler.unhandled", extra={"error": str(exc)})
