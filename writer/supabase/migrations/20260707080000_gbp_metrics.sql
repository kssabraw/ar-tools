-- Migration: 20260707080000_gbp_metrics.sql
-- Purpose: Google Business Profile (GBP) performance-metrics ingestion.
--   The suite already captures the GBP *profile + reviews* (via DataForSEO/
--   Outscraper, stored on clients.gbp). This adds the missing time-series
--   engagement metrics — impressions (maps/search × desktop/mobile), call
--   clicks, website clicks, direction requests, conversations — pulled from
--   Google's Business Profile Performance API with the same agency service
--   account used for GSC (Organic Rank Tracker #4). Closes the "GBP metric
--   growth" gap called out in docs/modules/client-reporting-prd-v1_0.md (Phase 2).
--
--   Dormant until access lands: the whole path is gated on settings
--   `gbp_metrics_enabled` (default false). It goes live once (a) Google approves
--   Business Profile API quota for the GCP project and (b) the service account is
--   added as a Manager on each client's Business Profile — the per-client
--   onboarding equivalent of "add the SA to your GSC property".
--
--   Tables (mirrors the GSC ingest data model — 20260622181933_gsc_ingest_storage):
--     * gbp_locations   — per-client registered GBP location + access state
--                         (the Performance API keys on `locations/{id}`, NOT the
--                          Place ID we already store; resolved via the Business
--                          Information API's accounts.locations.list).
--     * gbp_metric_daily— long/narrow daily metric dump (one row per
--                          location×date×metric); idempotent upsert on that key.
--     * gbp_sync_runs   — per-location ingest audit log (sibling of sync_runs,
--                          which is FK-bound to gsc_properties and can't be reused).
--
-- Access pattern (locked): RLS enabled, NO client-facing policies — written by
-- the scheduled ingest job and read by the platform-api, both with the
-- service-role key. Authorization is API-layer. (async_jobs pattern.)

-- ============================================================
-- gbp_locations — a client's registered GBP location + access state.
-- One client can have several locations (multi-location businesses); each is
-- verified + synced independently. `location_id` is the API resource name
-- ('locations/1234567890'); `account_id` its parent ('accounts/...').
-- ============================================================
create table if not exists gbp_locations (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  location_id    text not null,               -- 'locations/{locationId}' (Performance API key)
  account_id     text,                        -- 'accounts/{accountId}' (parent, from Business Information API)
  place_id       text,                        -- links back to clients.gbp.place_id when known
  title          text,                        -- human label for the location
  access_status  text not null default 'pending'
                   check (access_status in ('ok', 'no_access', 'pending', 'error')),
  last_verified_at timestamptz,
  last_synced_at   timestamptz,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint uq_gbp_locations_client_location unique (client_id, location_id)
);

create index if not exists idx_gbp_locations_client
  on gbp_locations (client_id);
create index if not exists idx_gbp_locations_access
  on gbp_locations (access_status);

-- ============================================================
-- gbp_metric_daily — raw daily metric dump. Long/narrow (metric-as-row) so new
-- metrics are additive with no schema change, mirroring gsc_query_daily's
-- additive shape. One row per (location, date, metric); idempotent upsert.
-- `value` is a non-negative daily count (bigint headroom for large listings).
-- ============================================================
create table if not exists gbp_metric_daily (
  location_row_id uuid not null references gbp_locations(id) on delete cascade,
  date            date not null,
  metric          text not null,             -- e.g. 'CALL_CLICKS', 'BUSINESS_IMPRESSIONS_MOBILE_MAPS'
  value           bigint not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint gbp_metric_daily_pkey primary key (location_row_id, date, metric)
);

-- Growth windows scan (location, date); per-metric series lookups too.
create index if not exists idx_gbp_metric_daily_loc_date
  on gbp_metric_daily (location_row_id, date);
create index if not exists idx_gbp_metric_daily_loc_metric
  on gbp_metric_daily (location_row_id, metric);

-- ============================================================
-- gbp_sync_runs — per-location ingest audit log + observability. Sibling of
-- sync_runs (which references gsc_properties and so can't carry GBP locations).
-- ============================================================
create table if not exists gbp_sync_runs (
  id              uuid primary key default gen_random_uuid(),
  location_row_id uuid not null references gbp_locations(id) on delete cascade,
  run_at          timestamptz not null default now(),
  start_date      date,
  end_date        date,
  rows            integer not null default 0,
  status          text not null check (status in ('ok', 'failed')),
  error           text
);

create index if not exists idx_gbp_sync_runs_loc_run_at
  on gbp_sync_runs (location_row_id, run_at desc);

-- ============================================================
-- Widen async_jobs.job_type so the scheduler can enqueue 'gbp_metrics_ingest'.
-- Strictly additive: the array is the union of every worker-dispatched job type
-- (incl. maps_image_backfill, omitted from 20260707050000) plus legacy values
-- with history rows still present, plus the new 'gbp_metrics_ingest'.
-- ============================================================
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
    'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel',
    'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest'
  ]));

-- ============================================================
-- RLS: enabled, no policies (service-role only).
-- ============================================================
alter table gbp_locations   enable row level security;
alter table gbp_metric_daily enable row level security;
alter table gbp_sync_runs   enable row level security;
