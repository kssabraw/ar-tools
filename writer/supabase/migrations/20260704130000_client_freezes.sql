-- Migration: 20260704130000_client_freezes.sql
-- Purpose: Freeze Protocol (Link Building SOP §Risk Monitoring & Freeze
--          Protocol / docs/sops/Link_Building_SOP.md). On a confirmed manual
--          action or site deindexing, the client is frozen: an alert lands on
--          the client card, all content creation AND link building pause
--          (router + job-worker gates read this table), and the Admins are
--          notified. A freeze is state, not just a notification — one row per
--          freeze episode, lifted explicitly by an admin.
--
--          Also widens async_jobs.job_type for the daily `freeze_check` job
--          (homepage deindex detection via GSC URL Inspection, with a
--          DataForSEO `site:` probe as a warn-only fallback).
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists client_freezes (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references clients(id) on delete cascade,
  reason     text not null
               check (reason in ('manual_action', 'deindexing', 'manual')),
  source     text not null default 'manual'
               check (source in ('manual', 'freeze_check')),
  note       text,
  details    jsonb,
  status     text not null default 'active'
               check (status in ('active', 'lifted')),
  created_at timestamptz not null default now(),
  lifted_at  timestamptz,
  lifted_by  text
);

-- Fast "is this client frozen?" lookup — the gate every content/link job runs.
create index if not exists idx_client_freezes_active
  on client_freezes (client_id) where status = 'active';
create index if not exists idx_client_freezes_client_created
  on client_freezes (client_id, created_at desc);

alter table client_freezes enable row level security;

-- Widen async_jobs.job_type (preserve the full set from 20260630120000_content_syndication).
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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel',
    'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item',
    'freeze_check'
  ]));
