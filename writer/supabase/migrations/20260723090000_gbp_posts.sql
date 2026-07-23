-- Migration: 20260723090000_gbp_posts.sql
-- Purpose: Google Business Profile (GBP) Posts module.
--   Compose (manual + AI-drafted) and publish GBP posts ("What's New" /
--   Event / Offer) to a client's Business Profile via Google's v4 localPosts
--   API, with scheduling, live-state reconciliation (LIVE/REJECTED), and
--   failure alerting through the shared notifications service.
--
--   Builds on the existing (dormant) GBP connection layer — gbp_locations
--   (20260707080000_gbp_metrics.sql) + the agency service account in
--   GOOGLE_SERVICE_ACCOUNT_KEY (business.manage scope). A client onboards by
--   adding the service account's client_email as a Manager on their Business
--   Profile (the per-client step, exactly like adding it to a GSC property).
--
--   Gated off by default: the whole surface no-ops until `gbp_api_enabled`
--   AND `gbp_posts_enabled` are set. See docs/modules/gbp-posts-module-prd-v1_0.md.
--
--   Tables (mirror the suite's async-jobs data-model conventions):
--     * gbp_post_schedules — per client+location recurring draft/auto-publish
--                            cadence, self-clocked on the shared scheduler.
--     * gbp_posts          — one row per post (draft → publishing → live |
--                            rejected | failed), plus soft-delete (Drafts).
--     * gbp_post_insights  — per-post view/CTA metrics (Phase 3; table now).
--
-- Access pattern (locked, matches gbp_metrics / async_jobs): RLS enabled, NO
-- client-facing policies — written by the API + scheduled jobs, both with the
-- service-role key. Authorization is enforced at the API layer.

-- ============================================================
-- gbp_post_schedules — recurring post cadence for one location.
-- Self-clocked via `next_run_at` on the shared gsc_scheduler loop (the
-- brand_scan_schedules pattern). Each tick AI-drafts a post; auto_publish
-- (opt-in per schedule) decides whether it publishes or waits for approval.
-- ============================================================
create table if not exists gbp_post_schedules (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  location_row_id uuid not null references gbp_locations(id) on delete cascade,
  cadence         text not null default 'disabled'
                    check (cadence in ('weekly', 'biweekly', 'monthly', 'disabled')),
  day_of_week     integer,                       -- 0=Mon … 6=Sun (weekly/biweekly)
  day_of_month    integer,                       -- 1..28 (monthly)
  hour_utc        integer not null default 9 check (hour_utc between 0 and 23),
  topic_type      text not null default 'standard'
                    check (topic_type in ('standard', 'event', 'offer')),
  theme_notes     text,                          -- rotation guidance fed to the draft prompt
  cta_type        text,                          -- default CTA for drafted posts
  cta_url         text,
  auto_publish    boolean not null default false,-- opt-in; default is draft-for-approval
  is_active       boolean not null default true,
  next_run_at     timestamptz,
  last_run_at     timestamptz,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint uq_gbp_post_schedules_client_location unique (client_id, location_row_id)
);

create index if not exists idx_gbp_post_schedules_due
  on gbp_post_schedules (is_active, next_run_at);

-- ============================================================
-- gbp_posts — a composed/published GBP post. Subtasks of publishing (state
-- reconciliation) key on `google_name` (the v4 resource name). Soft-delete
-- via deleted_at (Drafts tab), mirroring local_seo_pages.
-- ============================================================
create table if not exists gbp_posts (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  location_row_id uuid not null references gbp_locations(id) on delete cascade,
  schedule_id     uuid references gbp_post_schedules(id) on delete set null,
  source          text not null default 'manual'
                    check (source in ('manual', 'ai', 'schedule', 'external')),
  topic_type      text not null default 'standard'
                    check (topic_type in ('standard', 'event', 'offer')),
  summary         text not null default '',       -- body text (<= 1500 chars, enforced app-side)
  cta_type        text,                           -- book|order|shop|learn_more|sign_up|call (null = no CTA)
  cta_url         text,
  event           jsonb,                          -- {title, schedule:{start/end date/time}} (EVENT/OFFER)
  offer           jsonb,                          -- {couponCode, redeemOnlineUrl, termsConditions} (OFFER)
  media           jsonb,                          -- [{sourceUrl}] (public image URL)
  status          text not null default 'draft'
                    check (status in ('draft', 'scheduled', 'publishing', 'live',
                                      'rejected', 'failed', 'deleted')),
  scheduled_at    timestamptz,
  published_at    timestamptz,
  google_name     text,                           -- 'accounts/*/locations/*/localPosts/*'
  google_state    text,                           -- Google's PROCESSING | LIVE | REJECTED
  search_url      text,                           -- public URL of the live post
  error           text,
  created_by      uuid,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz                     -- soft-delete → Drafts tab
);

create index if not exists idx_gbp_posts_client
  on gbp_posts (client_id, created_at desc);
create index if not exists idx_gbp_posts_location
  on gbp_posts (location_row_id, created_at desc);
create index if not exists idx_gbp_posts_status
  on gbp_posts (status);
-- Sync idempotency: reconciling / importing a post upserts on its resource name.
create unique index if not exists uq_gbp_posts_location_google_name
  on gbp_posts (location_row_id, google_name) where google_name is not null;

-- ============================================================
-- gbp_post_insights — per-post view/CTA metrics (Phase 3). Long/narrow
-- (metric-as-row) so new metrics are additive; idempotent upsert per as_of.
-- ============================================================
create table if not exists gbp_post_insights (
  post_id    uuid not null references gbp_posts(id) on delete cascade,
  metric     text not null,                       -- LOCAL_POST_VIEWS_SEARCH | LOCAL_POST_ACTIONS_CALL_TO_ACTION
  value      bigint not null default 0,
  as_of      date not null,
  created_at timestamptz not null default now(),
  constraint gbp_post_insights_pkey primary key (post_id, metric, as_of)
);

-- ============================================================
-- Widen async_jobs.job_type so the worker/scheduler can enqueue the new
-- GBP-post job types. Strictly ADDITIVE: this is the exact LIVE constraint
-- set (pg_get_constraintdef, 2026-07-23) with the three new types appended,
-- so no existing job type is dropped.
-- ============================================================
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item', 'freeze_check', 'citation_check',
    'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel',
    'gbp_metrics_ingest', 'internal_link_analyze', 'internal_link_apply',
    'rank_keyword_report', 'local_seo_action', 'backlink_snapshot',
    'content_batch_item', 'task_month_generate', 'task_due_sweep',
    'task_import_asana', 'leadoff_tryout', 'leadoff_scout', 'leadoff_ai_probe',
    'domain_overview', 'keyword_gap', 'link_gap', 'leadoff_permits',
    'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh',
    'leadoff_city_finder', 'leadoff_income_backfill', 'leadoff_county_backfill',
    'keyword_research', 'ecommerce_generate', 'ecommerce_reoptimize_url',
    'ecommerce_action', 'github_infer_patterns', 'illustrate_run',
    'blog_github_publish',
    'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync'
  ]));

-- ============================================================
-- RLS: enabled, no policies (service-role only), matching gbp_metrics.
-- ============================================================
alter table gbp_post_schedules enable row level security;
alter table gbp_posts          enable row level security;
alter table gbp_post_insights  enable row level security;
