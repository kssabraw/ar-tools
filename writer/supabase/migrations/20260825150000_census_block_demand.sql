-- LeadOff GBP Placement Advisor — Census block-group demand cache
-- (docs/modules/leadoff-gbp-placement-plan-v1_0.md §6).
--
-- The free, $0 demand side of the placement advisor: US Census ACS 5-year data
-- at block-group resolution (households B25001, population B01003, median income
-- B19013, year-built buckets B25034) joined to TIGERweb block-group centroids.
-- Filled per-market on the first advisor run by the async `leadoff_placement`
-- job; placement zones are computed ON READ from this cache (like forecasting —
-- no result table). ~annual freshness (ACS updates yearly), so a market's
-- second read is a cheap DB hit.
--
-- App-owned public schema (NOT market_scanner, whose loader drop/recreates +
-- grant-strips its tables). Keyed by the 12-digit block-group GEOID; county_fips
-- (5-digit) indexed for the per-county cache-fill/refresh, and (lat,lng) for the
-- on-read bounding-box query that assembles a market's demand surface.
--
-- Grade safety (plan §7): this is a display/advice input only — nothing here
-- feeds the board grade, competitor_locations, or proximity_opportunity.

create table if not exists public.census_block_demand (
  geoid          text primary key,           -- 12-digit block-group GEOID
  county_fips    text not null,              -- 5-digit state+county FIPS
  lat            double precision not null,  -- TIGERweb block-group centroid
  lng            double precision not null,
  households     integer not null,           -- B25001_001E (housing units)
  population     integer,                     -- B01003_001E
  median_income  integer,                     -- B19013_001E (null = ACS no-data)
  housing_age    jsonb,                       -- B25034 year-built buckets
  pulled_at      timestamptz not null default now()
);

create index if not exists census_block_demand_county_idx
  on public.census_block_demand (county_fips);
create index if not exists census_block_demand_latlng_idx
  on public.census_block_demand (lat, lng);

-- RLS on with no policy (service-role only) — mirrors every sibling app-owned
-- LeadOff cache (competitor_locations, leadoff_gbp_pins, city_counties, …).
alter table public.census_block_demand enable row level security;
