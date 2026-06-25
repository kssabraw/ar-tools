-- Maps weak-zone geocoding (Module #5).
-- Turns the geo-grid's weakest pins into real place names so the team can act on
-- "where exactly are we weak, and which towns are there?". Two additions:
--
--   1. `maps_scan_results.report_weak_locations` — the per-keyword geocoded
--      output computed alongside the Local Rank Analysis report: each octant pin
--      enriched with its nearest city, plus the weak grid cells aggregated into
--      unique nearby localities (city, pin count, octants, worst rank, a
--      representative lat/lng). Shape:
--        {
--          "geocoded": bool, "capped": bool, "weak_threshold": int,
--          "octant_pins": [{lat,lng,octant,ring,radius_mi,strength,city,admin_area,formatted}],
--          "weak_areas":  [{city,admin_area,pins,octants,worst_rank,avg_rank,lat,lng}]
--        }
--
--   2. `maps_geocode_cache` — a tiny cross-client reverse-geocode cache keyed by
--      rounded lat/lng (≈11 m), so regenerating reports and overlapping grids
--      never re-bill the Google Geocoding API for the same coordinate. Mirrors
--      the keyword_market cross-client cache pattern.

alter table public.maps_scan_results
  add column if not exists report_weak_locations jsonb;

create table if not exists public.maps_geocode_cache (
  lat_key   numeric(8, 4) not null,   -- lat rounded to 4 dp (≈11 m)
  lng_key   numeric(8, 4) not null,
  city        text,                   -- locality / postal_town, when resolvable
  admin_area  text,                   -- state / province (administrative_area_level_1)
  formatted   text,                   -- Google's formatted_address
  place_id    text,
  created_at  timestamptz not null default now(),
  primary key (lat_key, lng_key)
);
