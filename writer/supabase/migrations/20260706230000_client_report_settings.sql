-- Migration: 20260706230000_client_report_settings.sql
-- Purpose: Client Reporting Phase 5 — delivery + scheduling.
--   * client_report_settings: per-client recipients + monthly/weekly schedule
--     (self-clocked via next_run_at on the shared gsc_scheduler, same pattern
--     as brand_scan_schedules) + per-channel delivery toggles.
--   * client_reports.delivery: per-channel delivery outcome (email/drive —
--     ok/failed/skipped), mirroring notifications.channels_sent.
--   * client_reports.report_type gains 'ai_visibility' — the AI Visibility
--     white-label report folded in as a report type (locked decision
--     2026-07-06; brand_report_html renders the body, this pipeline owns
--     PDF/storage/delivery).
-- RLS on, service-role only (matches client_reports).

create table if not exists client_report_settings (
  client_id     uuid primary key references clients(id) on delete cascade,
  recipients    text[] not null default '{}',   -- AM email(s); delivery skips when empty
  cadence       text not null default 'disabled'
                  check (cadence in ('disabled', 'weekly', 'monthly')),
  day_of_week   int,                            -- 0=Monday..6 (weekly)
  day_of_month  int check (day_of_month between 1 and 28),
  hour_utc      int not null default 8 check (hour_utc between 0 and 23),
  email_enabled bool not null default true,
  drive_enabled bool not null default true,
  last_run_at   timestamptz,
  next_run_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table client_report_settings enable row level security;

create index if not exists idx_client_report_settings_due
  on client_report_settings (next_run_at) where cadence <> 'disabled';

alter table client_reports add column if not exists delivery jsonb;

alter table client_reports drop constraint client_reports_report_type_check;
alter table client_reports
  add constraint client_reports_report_type_check
  check (report_type in ('monthly', 'weekly', 'ai_visibility'));
