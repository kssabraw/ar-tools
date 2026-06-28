-- Migration: 20260628060818_reopt_plans.sql
-- Purpose: Reoptimization planner — turns the rank tracker's signals (open
--          rank-drop alerts, rankability Quick wins, GSC-Research opportunities)
--          into a ranked, client-scoped list of recommended actions, each with a
--          deep link into the tool that does it. Stored per generation; surfaced
--          in an Action Plan view and pushed through the notifications service
--          (weekly digest + a refresh on a detected drop).
--
-- RLS on, NO client-facing policies (service-role only).

create table if not exists reopt_plans (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  trigger       text not null default 'scheduled'      -- scheduled | drop | manual
                  check (trigger in ('scheduled', 'drop', 'manual')),
  summary       text,
  items         jsonb,                                  -- the ranked action list
  action_count  integer not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists idx_reopt_plans_client
  on reopt_plans (client_id, created_at desc);

alter table reopt_plans enable row level security;

-- ============================================================
-- Widen async_jobs.job_type for the reopt_plan job (preserves the full current
-- set established in 20260628055434_async_jobs_jobtype_complete).
-- ============================================================
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan'
  ]));
