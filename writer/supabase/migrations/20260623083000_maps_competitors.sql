-- Migration: 20260623083000_maps_competitors.sql
-- Purpose: Maps geo-grid (#5) — store the per-keyword competitor leaderboard
--          captured from Local Dominator's GET /v1/scans/{uuid}/results
--          (detailsArray + compressed_grid → the top-20 businesses per pin).
--          `competitors` is a ranked list (top ~25 by local-pack presence) of
--          {place_id, name, rating, reviews, primary_category, website,
--           found_pins, top3_pins, top10_pins, avg_rank}, excluding the
--          client's own business. Powers the "who outranks us, and where"
--          report rollup (Share of Local Voice).

alter table maps_scan_results add column if not exists competitors jsonb;
