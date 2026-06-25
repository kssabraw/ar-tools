-- Country-aware neighborhood verification for the Local SEO silo planner.
--
-- The within-city check is no longer US-shaped (a "neighborhood" nested inside a
-- city's locality). To work worldwide — US neighborhoods, AU/UK suburbs that are
-- their own localities, etc. — it now verifies a candidate falls geographically
-- INSIDE the target city's geocoded footprint. That needs the city's bounding box
-- and the place's country, so cache them alongside the existing forward-geocode
-- fields. Additive + idempotent; existing rows get NULLs (treated as unknown).
alter table public.geocode_forward_cache
  add column if not exists country text,
  add column if not exists bounds  jsonb;  -- {ne_lat, ne_lng, sw_lat, sw_lng} (bounds || viewport)
