-- Migration: 20260826140000_client_report_ai_visibility_schedule.sql
-- Purpose: Client Reporting Phase 5 — let the recurring schedule also emit the
--   AI Visibility white-label report (report_type 'ai_visibility') alongside the
--   monthly/weekly combined PDF. Opt-in per client so existing schedules are
--   unchanged (default false); when on, the scheduler enqueues an ai_visibility
--   report on the same clock + delivery as the main report.
-- The 'ai_visibility' report_type already exists on client_reports (added in
--   20260706230000); this only adds the per-client schedule toggle.

alter table client_report_settings
  add column if not exists ai_visibility_enabled bool not null default false;
