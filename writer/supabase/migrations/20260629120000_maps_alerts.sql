-- Migration: 20260629120000_maps_alerts.sql
-- Purpose: Maps geo-grid tracker (Module #5) — scan-over-scan ANALYZER + in-app
--          ALERTING. When a scan completes, each keyword's newest scan is
--          compared to its previous completed scan; declines open episode-deduped
--          alerts that ride the shared notifications service (in-app + Slack).
--          Mirrors the Organic Rank Tracker's `rank_alerts` pattern, but keyed on
--          the keyword TEXT (maps_scan_results has no keyword_id FK).
--
-- Alert types (computed by the `maps_analyze` async job on scan completion):
--   - grid_rank_drop   : average grid rank worsened by >= threshold vs last scan
--   - coverage_drop    : Top-3 or Top-10 pin coverage % fell by >= threshold
--   - lost_pack        : went ranked->unranked in the core ring, or found-pin
--                        coverage collapsed (critical)
--   - area_decline     : a specific compass octant's coverage/avg-rank worsened
--                        (one episode per octant — `sector` is part of the key)
--   - competitor_surge : a competitor newly outranks the client on many pins
--
-- Episode model: at most ONE *open* (unresolved) alert per
-- (client_id, keyword, alert_type, sector). Opened when the condition first
-- holds; auto-resolved (resolved_at set) once it clears. status is read-state.
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

create table if not exists maps_alerts (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  scan_id       uuid references maps_scans(id) on delete set null,  -- the newer scan that opened it
  prev_scan_id  uuid references maps_scans(id) on delete set null,  -- the baseline compared against
  keyword       text not null,
  alert_type    text not null
                  check (alert_type in ('grid_rank_drop', 'coverage_drop',
                                        'lost_pack', 'area_decline',
                                        'competitor_surge')),
  sector        text,                      -- compass octant for area_decline (null otherwise)
  from_value    numeric,                   -- baseline metric (avg rank / coverage % / pins)
  to_value      numeric,                   -- current metric
  delta         numeric,                   -- to − from (sign meaning is per-type)
  message       text not null,
  details       jsonb,
  status        text not null default 'unread'
                  check (status in ('unread', 'read', 'dismissed')),
  triggered_on  date not null default current_date,
  resolved_at   timestamptz,               -- set when the condition clears (recovery)
  read_at       timestamptz,
  dismissed_at  timestamptz,
  created_at    timestamptz not null default now()
);

-- At most one OPEN alert per (keyword, type, sector). `coalesce(sector,'')`
-- keeps two simultaneous area_decline octants as distinct episodes while folding
-- the null-sector types into a single key.
create unique index if not exists uq_maps_alerts_open
  on maps_alerts (client_id, keyword, alert_type, coalesce(sector, ''))
  where resolved_at is null;

create index if not exists idx_maps_alerts_client_status
  on maps_alerts (client_id, status);
create index if not exists idx_maps_alerts_client_created
  on maps_alerts (client_id, created_at desc);

alter table maps_alerts enable row level security;

-- Widen async_jobs.job_type for the maps_analyze job (preserve the full set
-- from 20260628211200_client_reports).
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
    'client_report', 'maps_analyze'
  ]));
