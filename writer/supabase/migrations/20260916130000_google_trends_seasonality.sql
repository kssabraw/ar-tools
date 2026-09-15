-- Migration: 20260916130000_google_trends_seasonality.sql
-- Purpose: Phase 4 follow-up — persist the Google Trends interest_over_time
--   seasonality profile per client × keyword × location so
--   trend_watch.build_demand_outlook can PREFER it over the Ads-volume-history
--   profile (keyword_market.monthly_searches) when it feeds the Forecast card's
--   "Seasonal demand outlook".
--
--   Trends relative-interest is a truer seasonality signal than DataForSEO Ads
--   volume history, so a stored profile wins; the Ads history stays the fallback
--   and is NEVER overwritten (it is a different signal, and volume weighting still
--   comes from keyword_market). The read is best-effort — a missing/empty table
--   degrades build_demand_outlook to exactly its pre-Trends behaviour.
--
--   The local_seasonal scan (run_local_seasonal_scan) upserts one row per keyword
--   here; it rides no google_trends_runs row, so source_run_id is the async_jobs
--   job id that produced it (provenance only, no FK).
--
-- Additive + idempotent. Ships dark behind settings.google_trends_enabled (nothing
-- writes here unless the module is used), RLS-on with no client-facing policies
-- (service-role only; API-layer client_id filtering — the suite single-tenant model).

create table if not exists google_trends_seasonality (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  keyword        text not null,
  location_code  integer not null,
  month_index    jsonb not null,                       -- {"1".."12": float}, 1.0 = the year's mean ("index" is reserved)
  peak_months    integer[] not null default '{}',
  low_months     integer[] not null default '{}',
  source_run_id  uuid,                                 -- the async_jobs job id that produced it (provenance)
  updated_at     timestamptz not null default now(),
  unique (client_id, keyword, location_code)
);

create index if not exists google_trends_seasonality_client_kw_idx
  on google_trends_seasonality (client_id, keyword);

alter table google_trends_seasonality enable row level security;
