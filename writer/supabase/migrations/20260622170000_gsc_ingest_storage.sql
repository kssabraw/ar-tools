-- Migration: 20260622170000_gsc_ingest_storage.sql
-- Purpose: Organic Rank Tracker (Module #4) — M2 "Sync + storage".
--          Raw GSC query×date dump + per-run ingestion observability, and
--          widen async_jobs.job_type so the scheduler can enqueue ingest jobs.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §5, §6.
--
-- Access pattern (locked): RLS enabled, NO client-facing policies — written by
-- the scheduled ingest job and read by the platform-api, both with the
-- service-role key. Authorization is API-layer by property_id. (async_jobs
-- pattern, see 20260430120100_rls.sql.)

-- ============================================================
-- gsc_query_daily — raw GSC query×date dump (NO page dimension).
-- The "striking distance" discovery surface + the source the materialized
-- date axis (keyword_metrics, M3) is filtered from. One row per
-- (property, date, query); idempotent upsert on that key.
-- ============================================================
create table if not exists gsc_query_daily (
  property_id  uuid not null references gsc_properties(id) on delete cascade,
  date         date not null,
  query        text not null,
  clicks       integer not null default 0,
  impressions  integer not null default 0,
  ctr          double precision not null default 0,
  position     double precision,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint gsc_query_daily_pkey primary key (property_id, date, query)
);

-- Striking-distance + recency scans hit (property, date); query lookups too.
create index if not exists idx_gsc_query_daily_property_date
  on gsc_query_daily (property_id, date);
create index if not exists idx_gsc_query_daily_property_query
  on gsc_query_daily (property_id, query);

-- ============================================================
-- sync_runs — per-property ingestion audit log + observability.
-- Distinct from async_jobs (the generic worker queue): this records the
-- OUTCOME of each ingest (rows written, ok/failed, error). 403s recorded
-- here surface the "reconnect needed" state in the UI.
-- ============================================================
create table if not exists sync_runs (
  id           uuid primary key default gen_random_uuid(),
  property_id  uuid not null references gsc_properties(id) on delete cascade,
  job_type     text not null,                 -- e.g. 'gsc_query_daily'
  run_at       timestamptz not null default now(),
  start_date   date,
  end_date     date,
  rows         integer not null default 0,
  status       text not null
                 check (status in ('ok', 'failed')),
  error        text
);

create index if not exists idx_sync_runs_property_run_at
  on sync_runs (property_id, run_at desc);

-- ============================================================
-- Widen async_jobs.job_type so the GSC scheduler can enqueue ingest jobs.
-- (Same drop/re-add pattern as 20260501202328_silo_candidates.sql.)
-- ============================================================
alter table async_jobs
  drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest'));

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table gsc_query_daily enable row level security;
alter table sync_runs       enable row level security;
