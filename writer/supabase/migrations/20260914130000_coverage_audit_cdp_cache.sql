-- Migration: 20260914130000_coverage_audit_cdp_cache.sql
-- Purpose: Coverage Audit Phase 3 (Tier 3 — CDP × main-service). Adds the
--   per-state Census-Designated-Places (CDP) enumeration cache that
--   services/census_cdp.py fills from the TIGERweb Places/CDP ArcGIS-REST layer
--   (a DIFFERENT layer than census_demand.py's block-group layer, same
--   tigerweb.geo.census.gov host — this is the new, worker-only census query;
--   census.gov is egress-blocked from the sandbox).
--
--   Enumerating a state's CDPs is a static, deterministic pull (CDP boundaries
--   change only with a TIGER vintage, ~yearly), so it is cached PER STATE (keyed
--   by 2-digit state FIPS) and shared across every client in that state — the
--   Tier-3 location axis is then derived on read by pre-filtering the state's
--   CDPs to the service-area footprint bbox and geocode-verifying containment
--   (reusing geocode_forward_cache), so this table is the ONLY new storage the
--   tier needs. Containment verification reuses the existing geocode_forward_cache
--   (maps_geocode.forward_geocode_places); Tier 3 reuses the existing
--   'coverage_audit' async-job type (one job per tier), so NO async_jobs change.
--
--   Design: docs/modules/coverage-audit-module-plan-v1_0.md (§3.2, §8 Major #2)
--   + docs/modules/coverage-audit-handoff.md (Phase 3 scope).
--
-- RLS-on with no client-facing policies: access is service-role only (suite
-- single-tenant model), matching census_block_demand / geocode_forward_cache.
-- Additive + idempotent (IF NOT EXISTS).

create table if not exists census_cdp_cache (
  state_fips  text primary key,          -- 2-digit state FIPS ('06' = CA)
  cdps        jsonb not null default '[]'::jsonb,  -- [{name, geoid, lat, lng}]
  pulled_at   timestamptz not null default now()
);

alter table census_cdp_cache enable row level security;
