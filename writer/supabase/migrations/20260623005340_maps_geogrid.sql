-- Migration: 20260623005340_maps_geogrid.sql
-- Purpose: Maps / local-pack geo-grid ranker (Module #5). Per-client geo-grid
--          scans via the Local Dominator API: the team picks a 3/5/7-mile
--          radius (1-mile pin spacing) around the client's business, tracks
--          keywords, and sees a heatmap of the business's Maps rank per pin
--          plus a trend over time. Runs weekly on the shared scheduler, with an
--          on-demand "Run scan now".
--
-- Provider: Local Dominator (https://api.localdominator.co) — POST /v1/scans
-- (async, returns scan_uuid) → poll GET /v1/scans/{uuid}/results. grid_size is
-- capped at 21 by the API; our presets are 7/11/15 (3/5/7 mi @ 1-mile spacing).
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

-- ============================================================
-- maps_scan_configs — one geo-grid setup per client.
-- ============================================================
create table if not exists maps_scan_configs (
  client_id         uuid primary key references clients(id) on delete cascade,
  google_place_id   text,                       -- Google Place ID (from clients.gbp_place_id or entered)
  business_name     text,
  center_lat        double precision,
  center_lng        double precision,
  radius_miles      integer not null default 5 check (radius_miles in (3, 5, 7)),
  shape             text not null default 'square' check (shape in ('circle', 'square')),
  resource_category text not null default 'googleMaps'
                      check (resource_category in ('googleMaps', 'googleLocalFinder')),
  serp_device       text not null default 'desktop'
                      check (serp_device in ('desktop', 'mobile', 'both')),
  cadence           text not null default 'weekly' check (cadence in ('off', 'weekly')),
  weekday           integer not null default 1 check (weekday >= 0 and weekday <= 6),
  active            boolean not null default true,
  last_scanned_at   timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- ============================================================
-- maps_keywords — the search terms tracked for a client's grid.
-- ============================================================
create table if not exists maps_keywords (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  keyword     text not null,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  constraint maps_keywords_client_keyword_unique unique (client_id, keyword)
);

create index if not exists idx_maps_keywords_client on maps_keywords (client_id);

-- ============================================================
-- maps_scans — one row per scan run (a Local Dominator scan_uuid).
-- ============================================================
create table if not exists maps_scans (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id) on delete cascade,
  scan_uuid         text,                       -- Local Dominator scan identifier
  status            text not null default 'pending'
                      check (status in ('pending', 'polling', 'complete', 'failed')),
  trigger           text not null default 'scheduled' check (trigger in ('scheduled', 'manual')),
  grid_size         integer,
  distance          integer,                    -- metres between pins
  shape             text,
  radius_miles      integer,
  center_lat        double precision,
  center_lng        double precision,
  resource_category text,
  serp_device       text,
  search_terms      jsonb,                       -- keywords sent on this scan
  error             text,
  requested_at      timestamptz not null default now(),
  completed_at      timestamptz,
  created_at        timestamptz not null default now()
);

create index if not exists idx_maps_scans_client on maps_scans (client_id, created_at desc);
create index if not exists idx_maps_scans_status on maps_scans (status);

-- ============================================================
-- maps_scan_results — per-keyword result within a scan: the business's rank
-- per pin (rank_grid) plus rollups. One row per (scan, keyword).
-- ============================================================
create table if not exists maps_scan_results (
  id            uuid primary key default gen_random_uuid(),
  scan_id       uuid not null references maps_scans(id) on delete cascade,
  client_id     uuid not null references clients(id) on delete cascade,  -- for trend queries
  keyword       text not null,
  average_rank  numeric,                        -- mean of our rank over pins where we appear
  found_pins    integer not null default 0,
  total_pins    integer not null default 0,
  top3_pins     integer not null default 0,     -- pins where our rank <= 3 (local pack)
  top10_pins    integer not null default 0,
  rank_grid     jsonb,                           -- 2-D array [row][col] of our rank (null where absent)
  created_at    timestamptz not null default now()
);

create index if not exists idx_maps_scan_results_scan on maps_scan_results (scan_id);
create index if not exists idx_maps_scan_results_trend on maps_scan_results (client_id, keyword, created_at desc);

-- ============================================================
-- Widen async_jobs.job_type for the maps scan create job.
-- ============================================================
alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
                      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
                      'serp_snapshot', 'maps_scan'));

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table maps_scan_configs enable row level security;
alter table maps_keywords      enable row level security;
alter table maps_scans         enable row level security;
alter table maps_scan_results  enable row level security;
