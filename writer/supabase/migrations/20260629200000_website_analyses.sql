-- Migration: 20260629200000_website_analyses.sql
-- Purpose: On-site content comparison (Maps strategy PRD, Tier B / B5). For a
--          keyword, compares the client's ranking page against the top organic
--          competitor pages on content depth (word count) and topic coverage
--          (section headings competitors cover that the client doesn't), so
--          "expand your page" becomes a concrete recommendation. Captured by the
--          async `content_intel` job (DataForSEO SERP + ScrapeOwl).
--
-- One row per (client_id, keyword) capture. RLS on, service-role only.

create table if not exists website_analyses (
  id                          uuid primary key default gen_random_uuid(),
  client_id                   uuid not null references clients(id) on delete cascade,
  keyword                     text not null,
  client_url                  text,
  client_word_count           integer,
  competitor_median_word_count integer,
  depth_behind                integer,          -- competitor_median − client (positive = thinner)
  topic_gaps                  jsonb,            -- headings on >= half competitors the client lacks
  competitor_urls             jsonb,            -- the competitor pages compared
  captured_at                 timestamptz not null default now(),
  created_at                  timestamptz not null default now()
);

create index if not exists idx_website_analyses_client_captured
  on website_analyses (client_id, captured_at desc);
create index if not exists idx_website_analyses_client_keyword
  on website_analyses (client_id, keyword, captured_at desc);

alter table website_analyses enable row level security;

-- Widen async_jobs.job_type for the content_intel job (preserve the full set
-- from 20260629190000_backlink_profiles).
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
    'backlink_intel', 'content_intel'
  ]));
