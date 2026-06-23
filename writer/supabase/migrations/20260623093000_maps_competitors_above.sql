-- Migration: 20260623093000_maps_competitors_above.sql
-- Purpose: Maps geo-grid (#5) — store, per pin, the businesses ranking ABOVE the
--          client (everyone at/below is discarded). Captured from Local
--          Dominator's compressed_grid (rank-ordered indices into detailsArray):
--          for each in-circle pin we keep the slice ranked better than the
--          client. Shape:
--            { "directory": { "<place_id>": {name, rating, reviews,
--                              primary_category, website, lat, lng} },
--              "grid": [[ per-pin: [[place_id, rank], ...] | null ]] }
--          Powers "who outranks us, and on which pins" (per-pin local pack +
--          an outranks-us rollup), without storing the below-us long tail.

alter table maps_scan_results add column if not exists competitors_above jsonb;
