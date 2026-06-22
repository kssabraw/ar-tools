-- Migration: 20260622200000_keyword_market.sql
-- Purpose: Organic Rank Tracker (Module #4) — keyword market data.
--          CPC / search volume / competition from DataForSEO (Google Ads),
--          cached cross-client by (keyword, location) and refreshed monthly.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §4, §5, §6.
--
-- Keyword-level market data is NOT per-property: the same (keyword, location)
-- numbers are reused across clients, so cache once. RLS on, no client-facing
-- policies (service-role only).

create table if not exists keyword_market (
  keyword        text not null,
  location_code  integer not null,        -- DataForSEO location (national)
  search_volume  integer,
  cpc            double precision,
  competition    text,                    -- LOW / MEDIUM / HIGH (DataForSEO label)
  refreshed_at   timestamptz not null default now(),
  constraint keyword_market_pkey primary key (keyword, location_code)
);

-- Widen async_jobs.job_type for the monthly market refresh.
alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest',
                      'gsc_materialize', 'dataforseo_rank', 'keyword_market'));

alter table keyword_market enable row level security;
