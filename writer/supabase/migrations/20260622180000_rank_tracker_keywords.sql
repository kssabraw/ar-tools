-- Migration: 20260622180000_rank_tracker_keywords.sql
-- Purpose: Organic Rank Tracker (Module #4) — M3 "Materialize + status + UI".
--          Tracked keywords + the materialized per-keyword-per-day date axis.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §5, §7.
--
-- NOTE: the metrics table is named `rank_keyword_metrics` (not the PRD's bare
-- `keyword_metrics`) to avoid overloading "keyword" across the suite (the
-- Keyword Research module) and a ghost `keyword_metrics` migration in the log.
--
-- Access pattern (locked): RLS enabled, NO client-facing policies — written by
-- the materialize job and read by the platform-api with the service-role key.

-- ============================================================
-- tracked_keywords — the user-defined keywords tracked for a property.
-- `status` is COMPUTED nightly from the trend (not user-set); see §7.
-- ============================================================
create table if not exists tracked_keywords (
  id                   uuid primary key default gen_random_uuid(),
  property_id          uuid not null references gsc_properties(id) on delete cascade,
  keyword              text not null,
  source               text not null default 'gsc'
                         check (source in ('gsc', 'dataforseo', 'both')),
  canonical_url        text,
  canonical_url_locked boolean not null default false,
  status               text not null default 'no_data'
                         check (status in ('climbing', 'stable', 'volatile',
                                           'dropping', 'deindex_risk', 'no_data')),
  status_updated_at    timestamptz,
  active               boolean not null default true,
  created_by           uuid references profiles(id),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint tracked_keywords_property_keyword_unique unique (property_id, keyword)
);

create index if not exists idx_tracked_keywords_property
  on tracked_keywords (property_id);

-- ============================================================
-- rank_keyword_metrics — THE MATERIALIZED DATE AXIS.
-- Exactly one row per tracked keyword per day across the analysis window.
-- gsc_position is NULL on days GSC returned nothing (absence is STORED, not
-- omitted — the gap the trendline must render). gsc_position = GSC averaged;
-- tracked_rank = DataForSEO live (NULL until M4). Written by separate jobs.
-- ============================================================
create table if not exists rank_keyword_metrics (
  keyword_id    uuid not null references tracked_keywords(id) on delete cascade,
  date          date not null,
  clicks        integer not null default 0,
  impressions   integer not null default 0,
  ctr           double precision not null default 0,
  gsc_position  double precision,        -- NULL = GSC returned no row that day
  tracked_rank  integer,                 -- DataForSEO live (M4)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint rank_keyword_metrics_pkey primary key (keyword_id, date)
);

create index if not exists idx_rank_keyword_metrics_keyword_date
  on rank_keyword_metrics (keyword_id, date);

-- ============================================================
-- Widen async_jobs.job_type for the materialize+status job (chained after
-- ingest). Same drop/re-add pattern as prior migrations.
-- ============================================================
alter table async_jobs
  drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize'));

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table tracked_keywords    enable row level security;
alter table rank_keyword_metrics enable row level security;
