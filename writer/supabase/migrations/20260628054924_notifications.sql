-- Migration: 20260628054924_notifications.sql
-- Purpose: Suite notifications service — the shared delivery pipe for in-app
--          alerts (client-card badge + feed), email, and Slack. First producer
--          is the rank-drop alerting; the reoptimization planner follows.
--
-- emit() writes a notifications row (the in-app feed) and enqueues a
-- `notification_dispatch` async job that sends the email + Slack copies
-- best-effort (decoupled from producers so a blocking send can't stall a job).
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

create table if not exists notifications (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references clients(id) on delete cascade,   -- null = suite-wide
  kind          text not null,                                   -- 'rank_drop' | 'reopt_plan' | ...
  severity      text not null default 'info'
                  check (severity in ('info', 'warning', 'critical')),
  title         text not null,
  summary       text,
  payload       jsonb,                                           -- structured detail + a deep link
  status        text not null default 'unread'
                  check (status in ('unread', 'read', 'dismissed')),
  channels_sent jsonb,                                           -- {email: ok|failed|skipped, slack: ...}
  created_at    timestamptz not null default now(),
  read_at       timestamptz
);

create index if not exists idx_notifications_client
  on notifications (client_id, created_at desc);
create index if not exists idx_notifications_unread
  on notifications (client_id) where status = 'unread';

alter table notifications enable row level security;

-- ============================================================
-- Widen async_jobs.job_type for the notification_dispatch job
-- (preserves the current allowed set; same drop/re-add pattern as prior
-- rank-tracker migrations).
-- ============================================================
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
    'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
    'serp_snapshot', 'maps_scan', 'maps_report', 'page_structure_scrape',
    'local_seo_silo', 'gsc_research', 'service_page_plan', 'rank_location_derive',
    'notification_dispatch'
  ]));
