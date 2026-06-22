-- Migration: 20260622191240_gsc_query_page_daily.sql
-- Purpose: Organic Rank Tracker (Module #4) — query×page grain.
--          Powers canonical-URL resolution, the Pages view, and the per-keyword
--          page breakdown. Refreshed WEEKLY (the page dimension multiplies rows
--          and increases anonymization, so no daily granularity — PRD §6).
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §5, §6, §10.
--
-- KEPT SEPARATE from gsc_query_daily on purpose: GSC computes + anonymizes each
-- dimension grouping independently, so query×page totals will NOT reconcile
-- against query×date. RLS on, no client-facing policies (service-role only).

create table if not exists gsc_query_page_daily (
  property_id  uuid not null references gsc_properties(id) on delete cascade,
  date         date not null,
  query        text not null,
  page         text not null,
  clicks       integer not null default 0,
  impressions  integer not null default 0,
  ctr          double precision not null default 0,
  position     double precision,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint gsc_query_page_daily_pkey primary key (property_id, date, query, page)
);

create index if not exists idx_gsc_query_page_daily_property_query
  on gsc_query_page_daily (property_id, query);
create index if not exists idx_gsc_query_page_daily_property_page
  on gsc_query_page_daily (property_id, page);

-- Widen async_jobs.job_type for the weekly query×page ingest.
alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest',
                      'gsc_materialize', 'dataforseo_rank', 'keyword_market',
                      'gsc_page_ingest'));

alter table gsc_query_page_daily enable row level security;
