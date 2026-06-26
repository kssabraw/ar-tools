-- Migration: 20260626140000_clients_rank_location_source.sql
-- Purpose: Organic Rank Tracker (Module #4) — auto-derive a client's rank
--          tracking location from its Google Business Profile, unless the user
--          set one by hand.
--
-- `rank_tracking_location` / `rank_tracking_location_code` already exist
-- (20260622211331). This adds a provenance flag so auto-derivation never
-- clobbers a location a user picked:
--   * 'manual' — a team member set it via the UI; never auto-overwritten.
--   * 'auto'   — derived from the client's GBP; may be re-derived if the GBP
--                changes.
--   * NULL     — never set; eligible for auto-derivation.
-- And registers the `rank_location_derive` async job that does the derivation.

alter table clients
  add column if not exists rank_tracking_location_source text
    check (rank_tracking_location_source in ('auto', 'manual'));

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check
  check (job_type in (
    'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
    'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
    'serp_snapshot', 'maps_scan', 'maps_report', 'page_structure_scrape',
    'local_seo_silo', 'gsc_research', 'service_page_plan', 'rank_location_derive'
  ));
