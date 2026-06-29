-- Migration: 20260629130000_asana_task_templates.sql
-- Purpose: Asana monthly section automation, Feature A
--          (docs/modules/asana-task-integration-plan-v1_0.md §3).
--          The per-client task template: each client has its own editable list
--          of the tasks it should get every month. The monthly job reads these
--          rows (in sort order) and creates one Asana task per active row in a
--          freshly-created "<Month YYYY>" section, with Status=Not Started and
--          no due date. assignee_gid / category_option_gid are Asana GIDs
--          chosen in the editor (pickers populated from Asana); *_name columns
--          cache the display label so the editor renders without re-fetching.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

create table if not exists asana_client_task_templates (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references clients(id) on delete cascade,
  name                text not null,
  assignee_gid        text,          -- Asana user gid (nullable = unassigned)
  assignee_name       text,          -- cached display name for the editor
  category_option_gid text,          -- Asana enum-option gid for the category field
  category_name       text,          -- cached display name for the editor
  sort_order          integer not null default 0,
  active              boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index if not exists idx_asana_task_templates_client
  on asana_client_task_templates (client_id, sort_order);

alter table asana_client_task_templates enable row level security;

-- ============================================================
-- Widen async_jobs.job_type for the asana_monthly job (preserves the full
-- current set from 20260628060818_reopt_plans).
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
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'asana_monthly'
  ]));
