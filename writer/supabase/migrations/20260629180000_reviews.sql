-- Migration: 20260629180000_reviews.sql
-- Purpose: Review analytics (Maps strategy PRD, Tier B / B3). Stores individual
--          Google reviews for the client and its top local-pack competitors so
--          the team can compare review volume, velocity (reviews/month), rating
--          distribution and recent negatives — you vs competitors. Captured by
--          the async `review_intel` job (DataForSEO reviews, all ratings).
--
-- Reviews are immutable; `review_key` (a content hash) dedups across captures so
-- re-runs don't double-count. RLS on, service-role only (async_jobs pattern).

create table if not exists reviews (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  place_id      text not null,
  is_client     boolean not null default false,   -- the client's own listing vs a competitor's
  reviewer      text,
  rating        numeric,
  text          text,
  review_date   date,
  sentiment     text,                              -- reserved for a future LLM pass (B3 follow-up)
  review_key    text not null,                     -- md5(place_id|reviewer|date|text) — dedup key
  captured_at   timestamptz not null default now(),
  created_at    timestamptz not null default now()
);

create unique index if not exists uq_reviews_key on reviews (client_id, review_key);
create index if not exists idx_reviews_client_place on reviews (client_id, place_id);
create index if not exists idx_reviews_client_date on reviews (client_id, review_date desc);

alter table reviews enable row level security;

-- Widen async_jobs.job_type for the review_intel job (preserve the full set
-- from 20260629160000_competitor_gbp_profiles).
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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel'
  ]));
