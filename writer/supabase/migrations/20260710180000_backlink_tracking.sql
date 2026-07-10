-- Migration: 20260710180000_backlink_tracking.sql
-- Purpose: Backlink explorer Phase 4 — tracked targets, scheduled re-snapshots,
--   new/lost referring-domain diffing, alerts, and a daily paid-call budget.
--
--   * backlink_snapshots gains new_domains / lost_domains — the count of
--     referring domains gained/lost vs the target's previous snapshot (0 on the
--     first, baseline, snapshot so it never reads as "all N are new").
--   * backlink_usage — a per-day paid-call counter so an open "look up any
--     domain" box + scheduled re-pulls can't run past a daily DataForSEO budget.
--   * async_jobs.job_type gains 'backlink_snapshot' (scheduled re-capture of a
--     tracked target on the shared scheduler + the immediate first capture when
--     a target is marked tracked).

alter table backlink_snapshots add column if not exists new_domains integer;
alter table backlink_snapshots add column if not exists lost_domains integer;

create table if not exists backlink_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table backlink_usage enable row level security;

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item', 'freeze_check', 'citation_check',
    'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply',
    'rank_keyword_report', 'local_seo_action', 'backlink_snapshot'
  ])
);
