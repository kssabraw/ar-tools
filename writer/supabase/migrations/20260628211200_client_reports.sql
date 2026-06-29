-- Migration: 20260628211200_client_reports.sql
-- Purpose: Client Reporting module — generated client-facing PDF reports
--          (organic rankings, geo-grids, GA4, GBP analytics, Asana, campaign
--          health). Phase 0: the store + the report job type. PDFs land in the
--          private `reports` storage bucket (storage_path + a signed pdf_url); a
--          Drive-folder copy lands later (Phase 5, needs an Apps Script
--          extension). RLS on, NO client-facing policies (service-role only).

create table if not exists client_reports (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  report_type   text not null default 'monthly'
                  check (report_type in ('monthly', 'weekly')),
  period_start  date,
  period_end    date,
  status        text not null default 'pending'
                  check (status in ('pending', 'running', 'complete', 'failed')),
  storage_path  text,                 -- path within the `reports` bucket
  pdf_url       text,                 -- signed URL (regenerated on read as needed)
  drive_doc_id  text,                 -- Drive copy (Phase 5)
  sections      jsonb,                -- which sections were included + their status
  title         text,
  error         text,
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_client_reports_client
  on client_reports (client_id, created_at desc);

alter table client_reports enable row level security;

-- Private storage bucket for generated report PDFs (service-role + signed URLs).
insert into storage.buckets (id, name, public)
values ('reports', 'reports', false)
on conflict (id) do nothing;

-- Widen async_jobs.job_type for the client_report job (preserve the full set
-- from 20260628060818_reopt_plans).
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
    'client_report'
  ]));
