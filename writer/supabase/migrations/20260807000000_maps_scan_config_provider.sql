-- Migration: 20260807000000_maps_scan_config_provider.sql
-- Purpose: Let each client choose its Maps / local-pack geo-grid data source
--          (Local Dominator vs DataForSEO) instead of the single global
--          MAPS_SCAN_PROVIDER flag. Nullable: null = inherit the global default,
--          so every existing client keeps its current behaviour untouched.
--
-- Only NEW scans consult this setting. In-flight/historic scans keep finishing
-- on their own provider because the poller routes by the stored
-- maps_scans.provider column (stamped at scan start), not this config.

alter table maps_scan_configs
  add column if not exists provider text
    check (provider is null or provider in ('local_dominator', 'dataforseo'));
