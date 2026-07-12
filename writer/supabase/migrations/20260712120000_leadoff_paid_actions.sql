-- Migration: 20260712120000_leadoff_paid_actions.sql
-- Purpose: LeadOff paid actions (PRD §5 item 1) — the tryout (score any
--          off-list city, ~$0.20) and scout (RD + review velocity + demand
--          trend for one market, cache-cheapened) ported from the external
--          scanner's check_city.py / enrich_shortlist.py.
--
-- leadoff_tryouts: one row per tryout run — request, lifecycle, and the
--   per-category graded results (jsonb; the scanner tool saved these as
--   checked_cities/*.csv). App-side bookkeeping, so public schema — the
--   market_scanner schema stays scanner-owned.
-- leadoff_spend: the per-user daily budget ledger. Every paid enqueue
--   records its estimate up front; the guard sums today's rows (UTC).
-- async_jobs CHECK: rewritten preserving the FULL live set (which is wider
--   than any single repo migration file) + the two new job types.

create table if not exists leadoff_tryouts (
  id            uuid primary key default gen_random_uuid(),
  requested_by  uuid references profiles(id),
  city_id       bigint,                 -- market_scanner.cities id when resolved
  city_name     text not null,
  state_code    text not null,
  capture       double precision not null default 0.10,
  lead_tier     text not null default 'mid' check (lead_tier in ('low','mid','high')),
  status        text not null default 'pending'
                  check (status in ('pending','running','complete','failed')),
  results       jsonb,                  -- per-category graded rows (complete only)
  error         text,
  est_cost      numeric(8,2),
  created_at    timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_leadoff_tryouts_created
  on leadoff_tryouts (created_at desc);

alter table leadoff_tryouts enable row level security;

create table if not exists leadoff_spend (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid references profiles(id),
  action       text not null check (action in ('tryout','scout')),
  city_id      bigint,
  category_id  text,
  city_name    text,
  state_code   text,
  est_cost     numeric(8,2) not null,
  created_at   timestamptz not null default now()
);

create index if not exists idx_leadoff_spend_user_day
  on leadoff_spend (user_id, created_at desc);

alter table leadoff_spend enable row level security;

alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (job_type in (
  'website_scrape','page_structure_scrape','silo_dedup','gsc_ingest','gsc_page_ingest',
  'gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report',
  'serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate',
  'local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan',
  'rank_location_derive','brand_scan','brand_report','notification_dispatch',
  'reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp',
  'review_intel','backlink_intel','content_intel','local_relevance',
  'syndication_scan','syndication_item','freeze_check','citation_check',
  'page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan',
  'icp_scan','asana_push','competitor_intel','gbp_metrics_ingest',
  'internal_link_analyze','internal_link_apply','rank_keyword_report',
  'local_seo_action','backlink_snapshot','content_batch_item',
  'task_month_generate','task_due_sweep','task_import_asana',
  'leadoff_tryout','leadoff_scout'
));
