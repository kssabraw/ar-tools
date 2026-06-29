-- Migration: 20260629190000_backlink_profiles.sql
-- Purpose: Backlink profiling (Maps strategy PRD, Tier B / B4). Domain-level
--          backlink metrics (Domain Rating, referring domains, total backlinks)
--          for the client and its top local-pack competitors, as a time-series,
--          so the team can see authority gaps. Captured by the async
--          `backlink_intel` job (DataForSEO Backlinks summary).
--
-- One row per (client_id, domain, capture). RLS on, service-role only.

create table if not exists backlink_profiles (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id) on delete cascade,
  domain            text not null,
  is_client         boolean not null default false,
  domain_rating     numeric,                 -- DR-equivalent (DataForSEO rank, 0–1000)
  referring_domains integer,
  backlinks         integer,
  captured_at       timestamptz not null default now(),
  created_at        timestamptz not null default now()
);

create index if not exists idx_backlink_profiles_client_captured
  on backlink_profiles (client_id, captured_at desc);
create index if not exists idx_backlink_profiles_client_domain
  on backlink_profiles (client_id, domain, captured_at desc);

alter table backlink_profiles enable row level security;

-- Widen async_jobs.job_type for the backlink_intel job (preserve the full set
-- from 20260629180000_reviews).
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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel',
    'backlink_intel'
  ]));
