-- ============================================================
-- GA4 (Google Analytics) reporting — Client Reporting Phase 2.
--
-- The GA4 analogue of the GSC connection + daily-ingest tables. A client grants
-- the agency service account (the same client_email GSC/GBP use) Viewer access
-- on their GA4 property; the app then reads that property's data as the service
-- account over the GA4 Data API and stores a per-day rollup the client report
-- reads. DORMANT until settings.ga4_ingest_enabled is flipped on (after the
-- APIs are enabled + the SA is added as a Viewer — proven by
-- scripts/verify_ga4_api_access.py).
--
-- See docs/modules/client-reporting-prd-v1_0.md (Phase 2) and services/
-- ga4_service.py / services/ga4_ingest.py.
-- ============================================================

-- Connection state (mirrors gsc_properties).
create table if not exists ga4_properties (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  property_id      text not null,             -- "properties/123456789"
  display_name     text,                       -- from the Admin API, for the UI
  access_status    text not null default 'pending'
                     check (access_status in ('ok', 'no_access', 'pending')),
  last_verified_at timestamptz,
  created_by       uuid references profiles(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- One row per (client, property); a client could have more than one GA4
  -- property, but only a verified one is read for reporting.
  constraint ga4_properties_client_property_unique unique (client_id, property_id)
);

create index if not exists idx_ga4_properties_client_id on ga4_properties (client_id);

-- Per-day metric rollup (date-level totals + a channel-group session split).
-- One report is generated on demand over a window, so date granularity + the
-- channel breakdown is all the report needs — no per-URL / per-query axis.
create table if not exists ga4_daily (
  id                uuid primary key default gen_random_uuid(),
  property_id       uuid not null references ga4_properties(id) on delete cascade,
  date              date not null,
  sessions          integer not null default 0,
  total_users       integer not null default 0,
  screen_page_views integer not null default 0,
  -- Nullable: GA4 renamed "conversions" -> "keyEvents" in 2024; an older
  -- property or an unknown metric name leaves this null rather than failing the
  -- whole pull (see ga4_service.fetch_daily_metrics).
  conversions       integer,
  -- {channel_group: sessions}, e.g. {"Organic Search": 120, "Direct": 45}.
  channels          jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint ga4_daily_property_date_unique unique (property_id, date)
);

create index if not exists idx_ga4_daily_property_date on ga4_daily (property_id, date);

-- Ingest observability (mirrors sync_runs, but FK'd to ga4_properties since
-- sync_runs is bound to gsc_properties).
create table if not exists ga4_sync_runs (
  id          uuid primary key default gen_random_uuid(),
  property_id uuid not null references ga4_properties(id) on delete cascade,
  job_type    text not null default 'ga4_ingest',
  run_at      timestamptz not null default now(),
  start_date  date,
  end_date    date,
  rows        integer not null default 0,
  status      text not null check (status in ('ok', 'failed')),
  error       text
);

create index if not exists idx_ga4_sync_runs_property on ga4_sync_runs (property_id, run_at desc);

-- RLS: enabled, no policies (service-role only) — same posture as gsc_properties.
alter table ga4_properties enable row level security;
alter table ga4_daily enable row level security;
alter table ga4_sync_runs enable row level security;

-- ============================================================
-- async_jobs job_type: add 'ga4_ingest'. Preserves the FULL LIVE set (read from
-- the live constraint 2026-08-15, wider than any single repo migration file).
-- ============================================================
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type in (
    'website_scrape', 'page_structure_scrape', 'page_structure_parse',
    'silo_dedup', 'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize',
    'dataforseo_rank', 'keyword_market', 'gsc_research', 'rank_report',
    'serp_snapshot', 'maps_scan', 'maps_report', 'local_seo_silo',
    'local_seo_generate', 'local_seo_reoptimize_url', 'local_seo_reoptimize_page',
    'service_page_plan', 'rank_location_derive', 'brand_scan', 'brand_report',
    'notification_dispatch', 'reopt_plan', 'client_report', 'maps_analyze',
    'asana_monthly', 'competitor_gbp', 'review_intel', 'backlink_intel',
    'content_intel', 'local_relevance', 'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel', 'strategy_review',
    'maps_image_backfill', 'brand_voice_scan', 'icp_scan', 'asana_push',
    'competitor_intel', 'gbp_metrics_ingest', 'internal_link_analyze',
    'internal_link_apply', 'rank_keyword_report', 'local_seo_action',
    'backlink_snapshot', 'content_batch_item', 'task_month_generate',
    'task_due_sweep', 'task_import_asana', 'leadoff_tryout', 'leadoff_scout',
    'leadoff_ai_probe', 'domain_overview', 'keyword_gap', 'link_gap',
    'leadoff_permits', 'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh',
    'leadoff_city_finder', 'leadoff_income_backfill', 'leadoff_county_backfill',
    'keyword_research', 'ecommerce_generate', 'ecommerce_reoptimize_url',
    'ecommerce_action', 'github_infer_patterns', 'illustrate_run',
    'blog_github_publish', 'gbp_post_publish', 'gbp_post_generate',
    'gbp_posts_sync', 'site_inventory', 'website_provision',
    'website_theme_compile', 'website_core_pages', 'website_page_publish',
    'website_deploy_poll', 'website_page_generate',
    'deliverables_sheet_provision', 'deliverables_log', 'deliverable_notes_scan',
    'service_page_score', 'service_page_reoptimize', 'keyword_topic_research',
    'keyword_research_report', 'backlink_lookup', 'fanout_report', 'blog_score',
    'blog_reoptimize', 'fanout_expand', 'gbp_onboard', 'gbp_search_keywords',
    'ga4_ingest'
  )
);
