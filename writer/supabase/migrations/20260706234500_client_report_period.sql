-- Migration: 20260706234500_client_report_period.sql
-- Purpose: Client Reporting Phase 5 follow-up — user-selectable report
--   coverage. Scheduled reports can cover 30/60/90/120 days, 1 year, or the
--   whole campaign ('all' — anchored on clients.created_at). 'auto' keeps the
--   cadence-matched default (weekly → 7 days, monthly → 30).

alter table client_report_settings
  add column if not exists period text not null default 'auto'
    check (period in ('auto', '30d', '60d', '90d', '120d', '1y', 'all'));
