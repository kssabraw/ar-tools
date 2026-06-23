-- Migration: 20260623013849_maps_heatmap_image.sql
-- Purpose: Maps geo-grid (#5) — store Local Dominator's own rendered heatmap
--          image (pins on a Google Maps screenshot) per keyword result, plus a
--          link to its interactive page. Shown as the primary heatmap view.

alter table maps_scan_results add column if not exists heatmap_image_url text;
alter table maps_scan_results add column if not exists dynamic_url text;
