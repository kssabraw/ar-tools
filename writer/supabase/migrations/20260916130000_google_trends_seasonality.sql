-- Migration: 20260916130000_google_trends_seasonality.sql
-- Purpose: persist the Google Trends interest_over_time seasonality profile per
--   client × keyword × location so trend_watch.build_demand_outlook can surface it
--   on the Forecast card automatically (the §10 Phase-4 follow-up).
--
--   Today run_local_seasonal_scan returns its {outlook, profiles} on the async_jobs
--   row only, so it never reaches the client Forecast card. This table lets the
--   per-keyword Trends profile be read back by build_demand_outlook, which PREFERS
--   it (Trends relative-interest is a truer seasonality signal) over the Ads-volume
--   history in keyword_market.monthly_searches — WITHOUT overwriting that column
--   (Ads volume is a different signal, still the demand WEIGHT).
--
--   month_index is the {month: factor} map (1.0 = the year's mean), stored with
--   string month keys (jsonb); the reader coerces them back to ints. Named
--   month_index (not "index") to avoid the SQL reserved word.
--
--   source_run_id is the async_jobs id of the local_seasonal scan that wrote it
--   (no FK — job rows may be reaped). Upserted on (client_id, keyword, location_code).
--
-- RLS-on with no client-facing policies: access is service-role only (suite
-- single-tenant model). Ships dark behind settings.google_trends_enabled.

create table if not exists google_trends_seasonality (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  keyword        text not null,
  location_code  integer not null,
  month_index    jsonb not null default '{}'::jsonb,
  peak_months    integer[] not null default '{}',
  low_months     integer[] not null default '{}',
  source_run_id  uuid,
  updated_at     timestamptz not null default now(),
  unique (client_id, keyword, location_code)
);

create index if not exists google_trends_seasonality_client_idx
  on google_trends_seasonality (client_id, location_code);

alter table google_trends_seasonality enable row level security;
