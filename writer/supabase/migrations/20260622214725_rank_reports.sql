-- Migration: 20260622214725_rank_reports.sql
-- Purpose: Organic Rank Tracker (Module #4) — scheduled report config +
--          in-app generated-reports archive.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md.
--
-- RLS on, no client-facing policies (service-role only).

-- Per-client report schedule. One row per client; absent = 'as_needed'.
create table if not exists rank_report_config (
  client_id          uuid primary key references clients(id) on delete cascade,
  mode               text not null default 'as_needed'
                       check (mode in ('as_needed', 'weekly', 'monthly', 'interval')),
  day_of_week        integer check (day_of_week between 0 and 6),   -- weekly (0=Mon)
  day_of_month       integer check (day_of_month between 1 and 31), -- monthly
  interval_days      integer check (interval_days > 0),             -- every N days
  last_generated_at  timestamptz,
  updated_at         timestamptz not null default now()
);

-- Generated reports archive. snapshot = the full report data as-of generation.
create table if not exists rank_reports (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  title       text not null,
  snapshot    jsonb not null,
  created_by  uuid references profiles(id),
  created_at  timestamptz not null default now()
);

create index if not exists idx_rank_reports_client on rank_reports (client_id, created_at desc);

alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
                      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report'));

alter table rank_report_config enable row level security;
alter table rank_reports        enable row level security;
