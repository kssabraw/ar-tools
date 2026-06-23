-- Migration: 20260623011722_maps_shape_circle.sql
-- Purpose: Maps geo-grid ranker (#5) — the grid is always a CIRCLE. Drop the
--          square option from the default and normalize existing configs.
--          (Scans now always request shape='circle'; the column is kept for
--          history but no longer user-selectable.)

alter table maps_scan_configs alter column shape set default 'circle';
update maps_scan_configs set shape = 'circle' where shape is distinct from 'circle';
