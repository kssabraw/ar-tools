-- Migration: 20260625120000_gsc_research.sql
-- Purpose: GSC Research module — on-demand opportunity analysis from a LIVE
--          Search Console query×page pull. One run surfaces three opportunity sets:
--            1. Keyword cannibalization — a query split across multiple URLs that
--               all rank well, with impressions NOT clustered (Google can't decide).
--            2. Quick wins — query×page at position 6–10 (small push → page 1).
--            3. Hidden wins — query×page at position 11–30 with ≥5 impressions.
--          Quick/hidden wins are enriched with DataForSEO market data (CPC /
--          volume / competition) reusing the keyword_market service + cache.
--
-- Ported from the "GSC Research" n8n workflow. Results are stored per run as
-- JSONB so the in-app tables + CSV export render straight from the row.
-- RLS on, service-role only (matches the rest of the suite).

create table if not exists gsc_research_runs (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  status          text not null default 'pending'
                    check (status in ('pending', 'running', 'complete', 'failed')),
  trigger         text not null default 'manual',
  -- Whether a verified GSC property backed this run (false → empty results,
  -- the UI shows a "connect Search Console" state rather than an error).
  gsc_connected   boolean not null default false,
  -- The lookback window actually analyzed (last N days of ingested data).
  date_from       date,
  date_to         date,
  -- Result sets (one row per opportunity). Shapes documented in
  -- services/gsc_research.py.
  cannibalization jsonb not null default '[]'::jsonb,
  quick_wins      jsonb not null default '[]'::jsonb,
  hidden_wins     jsonb not null default '[]'::jsonb,
  -- Denormalized counts so the history list / dashboard can render without
  -- deserializing the full arrays.
  cannibalization_count integer not null default 0,
  quick_wins_count      integer not null default 0,
  hidden_wins_count     integer not null default 0,
  error           text,
  requested_at    timestamptz not null default now(),
  completed_at    timestamptz,
  created_at      timestamptz not null default now()
);

create index if not exists idx_gsc_research_runs_client
  on gsc_research_runs (client_id, created_at desc);

alter table gsc_research_runs enable row level security;

-- Allow the new on-demand analysis job type.
alter table public.async_jobs
  drop constraint if exists async_jobs_job_type_check;

alter table public.async_jobs
  add constraint async_jobs_job_type_check check (
    job_type = any (array[
      'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
      'serp_snapshot', 'maps_scan', 'maps_report', 'page_structure_scrape',
      'local_seo_silo', 'gsc_research'
    ])
  );
