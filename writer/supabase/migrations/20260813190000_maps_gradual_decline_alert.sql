-- Migration: 20260813190000_maps_gradual_decline_alert.sql
-- Purpose: Maps geo-grid tracker (Module #5) — add the `gradual_decline` alert
--          type (the local-pack analogue of the organic `gradual_drop`).
--
-- The scan-over-scan detectors (grid_rank_drop / coverage_drop / area_decline)
-- only fire when a metric worsens past a threshold vs the IMMEDIATELY PREVIOUS
-- scan. A keyword whose average grid rank bleeds ~0.4 spots/scan, or whose Top-3
-- pin coverage erodes a few points/scan, never crosses those per-scan bars — so
-- a slow multi-week local-pack decline opened no maps_alert and notified no one.
--
-- `gradual_decline` measures CUMULATIVE displacement (average grid rank AND/OR
-- Top-3 coverage) over a trailing ~8-week window of scheduled scans, fires only
-- when the slide is genuinely gradual (steady, not a cliff the scan-over-scan
-- rules already own, and suppressed when a sudden magnitude alert fires the same
-- scan), and rides the same notification + response-episode + Action Plan
-- machinery as the other types.
--
-- Detection lives in services/maps_analyzer.py::detect_gradual_decline; this
-- only widens the alert_type CHECK to accept the new value.

alter table maps_alerts drop constraint if exists maps_alerts_alert_type_check;

alter table maps_alerts add constraint maps_alerts_alert_type_check
  check (alert_type in ('grid_rank_drop', 'coverage_drop', 'lost_pack',
                        'area_decline', 'competitor_surge', 'gradual_decline'));
