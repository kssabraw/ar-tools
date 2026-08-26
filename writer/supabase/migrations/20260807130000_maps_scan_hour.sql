-- Per-client local-time scheduling for geo-grid scans.
--
-- Until now a client's scheduled scan fired on its `weekday` at a single global
-- UTC hour (settings.gsc_ingest_hour_utc). This adds an hour-of-day, expressed in
-- the CLIENT'S local timezone (clients.timezone, derived from the GBP/grid center)
-- so the team can say "scan Tuesday 6am local" and have it honored per client.
--
-- Default 8 (= 8am local). Existing rows adopt it; for US clients this lands the
-- scan on the same weekday it already ran, just at a business-hours local time
-- instead of the ~1-3am local time the fixed 08:00 UTC gate produced.
alter table maps_scan_configs
  add column if not exists scan_hour smallint not null default 8
    check (scan_hour >= 0 and scan_hour <= 23);
