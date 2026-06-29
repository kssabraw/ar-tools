-- Migration: 20260629210000_local_relevance_scores.sql
-- Purpose: Local Relevance Scorecard (Maps strategy PRD, Tier B / B6). For a
--          tracked keyword (service) + the client's location, scores — for the
--          client AND each top local-pack competitor — how well each ranking
--          signal aligns with the service/location actually being tracked:
--            * do their reviews mention the service / the location
--            * does their GBP link to a page that's about the service / location
--            * is their GBP category the service (or closely related)
--            * site Domain Rating + the GBP-linked page's URL Rating
--          All matching is deterministic (services/local_relevance.py).
--
-- One row per (client_id, keyword, place_id) capture. RLS on, service-role only.

create table if not exists local_relevance_scores (
  id                       uuid primary key default gen_random_uuid(),
  client_id                uuid not null references clients(id) on delete cascade,
  keyword                  text not null,         -- the tracked service term
  location                 text,                  -- the client's location used for matching
  place_id                 text,
  is_client                boolean not null default false,
  name                     text,
  domain                   text,
  gbp_url                  text,                  -- the website the GBP links to
  category                 text,
  category_match           text,                  -- 'exact' | 'related' | 'none'
  reviews_total            integer,
  reviews_service_mentions integer,
  reviews_location_mentions integer,
  page_service_relevant    boolean,
  page_location_relevant   boolean,
  domain_rating            numeric,               -- DR of the site
  page_ur                  numeric,               -- URL Rating of the GBP-linked page
  captured_at              timestamptz not null default now(),
  created_at               timestamptz not null default now()
);

create index if not exists idx_local_relevance_client_captured
  on local_relevance_scores (client_id, captured_at desc);
create index if not exists idx_local_relevance_client_keyword
  on local_relevance_scores (client_id, keyword, captured_at desc);

alter table local_relevance_scores enable row level security;

-- Widen async_jobs.job_type for the local_relevance job (preserve the full set
-- from 20260629200000_website_analyses).
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
    'client_report', 'maps_analyze', 'competitor_gbp', 'review_intel',
    'backlink_intel', 'content_intel', 'local_relevance'
  ]));
