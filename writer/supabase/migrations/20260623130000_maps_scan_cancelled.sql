-- Migration: 20260623130000_maps_scan_cancelled.sql
-- Purpose: Add a 'cancelled' status to maps_scans so an in-flight scan (pending
--          or polling) can be stopped by the user from the UI. The scan is
--          marked cancelled (and its queued create-job dropped) so the poller
--          no longer advances it. Deleting old runs hard-deletes the maps_scans
--          row; maps_scan_results already cascades (on delete cascade).

alter table maps_scans
  drop constraint maps_scans_status_check;
alter table maps_scans
  add constraint maps_scans_status_check
  check (status in ('pending', 'polling', 'complete', 'failed', 'cancelled'));
