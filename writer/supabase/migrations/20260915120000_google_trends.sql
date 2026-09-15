-- Migration: 20260915120000_google_trends.sql
-- Purpose: Google Trends Discovery module (shared core + Phase 1, ecommerce).
--   Pull RISING related queries from Google Trends (via the DataForSEO
--   keywords_data/google_trends/explore endpoint), qualify each with the
--   volume/CPC data the suite already buys (dataforseo_labs.fetch_keyword_overview),
--   score them (velocity × the existing opportunity model), and persist a run so
--   the view is a cheap re-read. An INPUT source, not a new pipeline — everything
--   downstream of a qualified rising query reuses existing modules.
--
--   * google_trends_runs      — one row per scan (seeds + category + rollup counts)
--   * google_trends_keywords  — child: every rising query + its qualified metrics
--   * google_trends_usage     — per-day paid-call meter (mirrors keyword_research_usage)
--   * reserve_google_trends_calls() — atomic check-and-increment (fail-closed caller)
--
--   Also widens async_jobs.job_type to add 'google_trends_scan'. The array below
--   is the FULL LIVE constraint set (read from pg_constraint on 2026-09-15, which
--   is wider than any single repo migration file) plus the new type, so applying
--   this never drops a live-only job type.
--
-- All tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).
-- Ships dark behind settings.google_trends_enabled (code default False).

-- ---------------------------------------------------------------------------
-- Runs (one per scan)
-- ---------------------------------------------------------------------------
create table if not exists google_trends_runs (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients (id) on delete cascade,
  seeds            text[] not null default '{}',
  category_code    integer,
  category_name    text,
  location_code    integer,
  language_code    text default 'en',
  trends_type      text not null default 'web',
  rising_count     integer not null default 0,
  qualified_count  integer not null default 0,
  status           text not null default 'complete',
  cost_usd         numeric,
  created_at       timestamptz not null default now()
);

create index if not exists google_trends_runs_client_idx
  on google_trends_runs (client_id, created_at desc);

alter table google_trends_runs enable row level security;

-- ---------------------------------------------------------------------------
-- Keywords (child of a run) — the rising queries + their qualified metrics
-- ---------------------------------------------------------------------------
create table if not exists google_trends_keywords (
  id                 uuid primary key default gen_random_uuid(),
  run_id             uuid not null references google_trends_runs (id) on delete cascade,
  query              text not null,
  seed               text,
  bucket             text not null default 'rising',
  rising_value       numeric,
  is_breakout        boolean not null default false,
  volume             integer,
  cpc_usd            numeric,
  competition_index  numeric,
  keyword_difficulty numeric,
  search_intent      text,
  is_question        boolean not null default false,
  qualified          boolean not null default false,
  trend_score        numeric
);

create index if not exists google_trends_keywords_run_idx
  on google_trends_keywords (run_id);

alter table google_trends_keywords enable row level security;

-- ---------------------------------------------------------------------------
-- Daily paid-call budget meter + atomic reservation (mirrors keyword_research_usage)
-- ---------------------------------------------------------------------------
create table if not exists google_trends_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table google_trends_usage enable row level security;

create or replace function reserve_google_trends_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into google_trends_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update google_trends_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;

-- ---------------------------------------------------------------------------
-- async_jobs job_type — add 'google_trends_scan' (FULL LIVE set preserved)
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'page_structure_parse', 'silo_dedup',
    'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank',
    'keyword_market', 'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan',
    'maps_report', 'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
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
    'leadoff_geocode', 'qa_review', 'leadoff_signal_refresh', 'leadoff_city_finder',
    'leadoff_income_backfill', 'leadoff_county_backfill', 'keyword_research',
    'ecommerce_generate', 'ecommerce_reoptimize_url', 'ecommerce_action',
    'github_infer_patterns', 'illustrate_run', 'blog_github_publish',
    'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync', 'site_inventory',
    'website_provision', 'website_theme_compile', 'website_core_pages',
    'website_page_publish', 'website_deploy_poll', 'website_page_generate',
    'deliverables_sheet_provision', 'deliverables_log', 'deliverable_notes_scan',
    'service_page_score', 'service_page_reoptimize', 'keyword_topic_research',
    'keyword_research_report', 'backlink_lookup', 'fanout_report', 'blog_score',
    'blog_reoptimize', 'fanout_expand', 'gbp_onboard', 'gbp_search_keywords',
    'fanout_plan', 'fanout_regate', 'fanout_fanout', 'fanout_architecture',
    'ga4_ingest', 'gbp_reviews', 'leadoff_map_refresh', 'leadoff_placement',
    'leadoff_zip_demand', 'voice_revalidate', 'autonomy_run', 'score_external',
    'everhour_mirror', 'everhour_sync', 'plan_handoff', 'local_seo_matrix_suggest',
    'local_seo_matrix_publish', 'guide_sync', 'gbp_profile_apply',
    'gbp_profile_draft', 'gbp_profile_sync', 'gbp_profile_monitor', 'social_publish',
    'social_fanout', 'coverage_audit',
    'google_trends_scan'
  ])
);
