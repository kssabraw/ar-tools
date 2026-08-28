-- Migration: 20260826150000_client_report_maps_schedule.sql
-- Purpose: Client Reporting Phase 5 — let the recurring schedule also emit a
--   standalone Local Rank (Google Maps geo-grid) report, mirroring the AI
--   Visibility wiring. Opt-in per client (default false) so existing schedules
--   are unchanged; adds the 'maps' report_type to client_reports.
-- The combined monthly/weekly PDF already carries a geo-grid section; this is
--   the fuller Maps-only deliverable folded in as its own report type.

alter table client_report_settings
  add column if not exists maps_enabled bool not null default false;

alter table client_reports drop constraint client_reports_report_type_check;
alter table client_reports
  add constraint client_reports_report_type_check
  check (report_type in ('monthly', 'weekly', 'ai_visibility', 'maps'));
