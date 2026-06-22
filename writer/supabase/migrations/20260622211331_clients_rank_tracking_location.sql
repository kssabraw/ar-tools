-- Migration: 20260622211331_clients_rank_tracking_location.sql
-- Purpose: Organic Rank Tracker (Module #4) — per-client tracking location.
--          The DataForSEO live-rank + keyword-market checks use this location
--          (a DataForSEO location_code at city/region/country granularity)
--          instead of the country auto-detected from the website TLD.
--          NULL = fall back to the auto-detected country (prior behavior).
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §2.

alter table clients add column if not exists rank_tracking_location text;
alter table clients add column if not exists rank_tracking_location_code integer;
