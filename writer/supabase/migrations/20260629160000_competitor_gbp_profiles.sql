-- Migration: 20260629160000_competitor_gbp_profiles.sql
-- Purpose: Competitor GBP intelligence (Maps strategy PRD, Tier B / B1). For the
--          top local-pack competitors surfaced by a client's geo-grid scans, we
--          fetch a full Google Business Profile (Outscraper) and store it as a
--          time-series so the team can see *why* a competitor wins a zone
--          (categories, review count/velocity, photos, hours) and audit gaps.
--
-- One row per (client_id, competitor place_id, capture). The async `competitor_gbp`
-- job inserts a fresh capture each run; reads take the latest per competitor.
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

create table if not exists competitor_gbp_profiles (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  place_id        text not null,
  name            text,
  primary_category text,
  gbp_categories  jsonb,                 -- list of category strings
  rating          numeric,
  review_count    integer,
  website         text,
  phone           text,
  address         text,
  photo           text,
  has_hours       boolean,
  -- Local-pack presence carried from the scan's competitor leaderboard (context
  -- for "how much does this competitor matter" without re-deriving it).
  found_pins      integer,
  top3_pins       integer,
  profile         jsonb,                 -- the full mapped GBP payload (categories, hours, reviews, …)
  captured_at     timestamptz not null default now(),
  created_at      timestamptz not null default now()
);

create index if not exists idx_competitor_gbp_client_captured
  on competitor_gbp_profiles (client_id, captured_at desc);
create index if not exists idx_competitor_gbp_client_place
  on competitor_gbp_profiles (client_id, place_id, captured_at desc);

alter table competitor_gbp_profiles enable row level security;

-- Widen async_jobs.job_type for the competitor_gbp job (preserve the full set
-- from 20260629120000_maps_alerts).
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'competitor_gbp'
  ]));
