-- Maps geo-grid: radius becomes a free per-client choice (1-10 whole miles)
-- instead of the 3/5/7-mile preset. Pin spacing stays 1 mile, so a radius r
-- scan is a (2r+1)x(2r+1) grid; the 10-mile cap bounds cost at a 21x21 grid.
-- The DataForSEO provider's pin zoom is derived from the radius
-- (maps_dataforseo.zoom_for_radius), so any radius in range keeps a correctly
-- sized viewport.

alter table maps_scan_configs
  drop constraint if exists maps_scan_configs_radius_miles_check;

alter table maps_scan_configs
  add constraint maps_scan_configs_radius_miles_check
  check (radius_miles between 1 and 10);
