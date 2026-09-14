-- Migration: 20260914120000_coverage_audit.sql
-- Purpose: Coverage Audit module (Phase 0 foundations). A whole-site location &
--   service gap finder: scans the client's site as it stands, infers which
--   service/location pages already exist, diffs the ideal service×location
--   universe against actual across four tiers, demand-ranks the gaps, and
--   auto-seeds a Service×Location Matrix per tier (AXES ONLY — the Matrix owns
--   per-cell coverage via its own mark_coverage; the audit never persists a
--   second coverage verdict). Design: docs/modules/coverage-audit-module-plan-v1_0.md.
--
--   * coverage_audits            — one run per client, jsonb-heavy (like
--                                  keyword_research_runs); re-opening a run is a read
--   * coverage_audit_usage       — per-day paid-call meter (mirrors
--                                  keyword_research_usage / domain_intel_usage)
--   * reserve_coverage_audit_calls() — atomic, fail-closed check-and-increment
--
--   Also widens async_jobs.job_type to add a single 'coverage_audit' type. The
--   audit runs ONE job PER TIER (plan §8 Major #3 — the per-tier decomposition
--   keeps each job under the 30-min stale-job reaper); the tier lives in the job
--   payload, not a separate job_type per tier. The array below is the FULL live
--   constraint set plus the new type, so applying this never drops a live-only
--   job type.
--
-- All tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).
-- Additive + idempotent throughout (IF NOT EXISTS / OR REPLACE / IF EXISTS).

-- ---------------------------------------------------------------------------
-- Runs (one per audit run) — jsonb-heavy like keyword_research_runs
-- ---------------------------------------------------------------------------
create table if not exists coverage_audits (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  status         text not null default 'pending',
  tier           integer,               -- which tier this run covers (1..4); one job/run per tier
  service_axis   jsonb,                  -- resolved (confirmed/edited) service axis
  location_axis  jsonb,                  -- resolved location universe (cities / CDPs / neighborhoods)
  gaps           jsonb,                  -- {missing_services, missing_locations, missing_cells}, demand-ranked
  provenance     jsonb,                  -- how each axis/source was derived + degraded notes
  error          text,
  created_at     timestamptz not null default now()
);

create index if not exists coverage_audits_client_idx
  on coverage_audits (client_id, created_at desc);

alter table coverage_audits enable row level security;

-- ---------------------------------------------------------------------------
-- Daily paid-call budget meter + atomic reservation (mirrors keyword_research_usage)
-- fail-closed: the UPDATE only lands while it stays under the cap, so a call that
-- would exceed the cap reserves nothing and RETURNS false.
-- ---------------------------------------------------------------------------
create table if not exists coverage_audit_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table coverage_audit_usage enable row level security;

create or replace function reserve_coverage_audit_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into coverage_audit_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update coverage_audit_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;

-- ---------------------------------------------------------------------------
-- async_jobs job_type — add 'coverage_audit' (FULL live set preserved)
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
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
    'website_deploy_poll', 'website_page_generate', 'deliverables_sheet_provision',
    'deliverables_log', 'deliverable_notes_scan', 'service_page_score',
    'service_page_reoptimize', 'keyword_topic_research', 'keyword_research_report',
    'backlink_lookup', 'fanout_report', 'blog_score', 'blog_reoptimize',
    'fanout_expand', 'gbp_onboard', 'gbp_search_keywords', 'fanout_plan',
    'fanout_regate', 'fanout_fanout', 'fanout_architecture', 'ga4_ingest',
    'gbp_reviews', 'leadoff_map_refresh', 'leadoff_placement',
    'leadoff_zip_demand', 'voice_revalidate', 'autonomy_run', 'score_external',
    'everhour_mirror', 'everhour_sync', 'plan_handoff',
    'local_seo_matrix_suggest', 'local_seo_matrix_publish', 'guide_sync',
    'gbp_profile_apply', 'gbp_profile_draft', 'gbp_profile_sync',
    'gbp_profile_monitor', 'social_publish', 'social_fanout',
    'coverage_audit'
  ])
);
