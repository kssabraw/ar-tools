-- Migration: 20260623012733_maps_scan_results_unique.sql
-- Purpose: Maps geo-grid (#5) — make scan-result storage idempotent so that
--          concurrent pollers (the shared scheduler + an on-demand poll while a
--          user watches) can't double-insert a keyword's result. One row per
--          (scan, keyword); pollers upsert on it.

delete from maps_scan_results a using maps_scan_results b
  where a.ctid < b.ctid and a.scan_id = b.scan_id and a.keyword = b.keyword;

alter table maps_scan_results
  add constraint maps_scan_results_scan_keyword_unique unique (scan_id, keyword);
