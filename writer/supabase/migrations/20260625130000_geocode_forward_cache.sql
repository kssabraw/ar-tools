-- Forward-geocode cache for the Local SEO silo planner's neighborhood discovery.
--
-- The "Plan Silo" flow proposes neighborhoods within a target city (Haiku), then
-- forward-geocodes each to VERIFY it's a real locality inside that city (and not
-- an adjacent town) before offering "<service> <neighborhood>" page targets.
--
-- Forward geocoding is keyed by the normalized query string ("neighborhood, city,
-- state, country"), unlike the reverse-geocode cache (`maps_geocode_cache`) which
-- is keyed by rounded lat/lng — so it gets its own table. Cross-client + no TTL:
-- a city's neighborhoods don't move, so a verified (or definitively rejected)
-- lookup is reused across clients and plan re-runs, never re-billing Google.
-- `matched=false` rows cache the negative result too (ZERO_RESULTS / wrong city /
-- not neighborhood-specific) so a known-bad name isn't re-queried.
create table if not exists public.geocode_forward_cache (
  query_norm  text primary key,            -- lower-cased, whitespace-collapsed query
  matched     boolean not null default false,
  city        text,
  admin_area  text,
  formatted   text,
  place_id    text,
  result_types text[],                     -- top result's Google place types
  lat         double precision,
  lng         double precision,
  created_at  timestamptz not null default now()
);

-- Service-role-only, like the rest of the suite's server-owned caches.
alter table public.geocode_forward_cache enable row level security;
