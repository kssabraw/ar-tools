-- Migration: 20260916180000_content_gap.sql
-- Purpose: Content Gap Analyzer module — Phase 0 foundations.
--   See docs/modules/content-gap-analyzer-prd-v1_0.md §7.
--
--   Per-client module: for selected money-pages × main keywords, check whether
--   the client is top-10 organic AND cited in the AI Overview; where not, diff
--   the competitors ranking above them across authority / traffic / entity /
--   on-page-content dimensions. An assembly/diff/presentation layer over
--   surfaces the suite already runs (serp_snapshots, nlp /analyze + /score-page,
--   dataforseo_labs, page_structure_eval) — it builds NO new scoring engine.
--
--   * content_gap_runs     — one row per (client, trigger, created_at) with
--                            summary rollups (keywords analyzed / wins / gaps).
--   * content_gap_keywords — one row per (run, keyword × page): verdict, the
--                            resolved competitor set, per-dimension gap payload,
--                            the on-page diff, and the serp_snapshot it read.
--   * content_gap_usage    — per-day paid-call meter (mirrors domain_intel_usage).
--   * reserve_content_gap_calls() — atomic check-and-increment (fail-closed,
--       copied from reserve_domain_intel_calls) so concurrent scans can't
--       overshoot the daily cap.
--
-- All tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).

-- ---------------------------------------------------------------------------
-- Runs (one per scan)
-- ---------------------------------------------------------------------------
create table if not exists content_gap_runs (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references clients (id) on delete cascade,
  trigger            text not null default 'manual'
                       check (trigger in ('scheduled', 'manual')),
  location_code      integer,
  language_code      text default 'en',
  entity_provider    text,           -- 'textrazor' | 'google' (resolved at run)
  status             text not null default 'pending'
                       check (status in ('pending', 'running', 'complete',
                                         'partial', 'failed')),
  cost_usd           numeric,
  -- summary rollups (filled as the run completes; nullable while pending)
  keywords_analyzed  integer,
  wins               integer,
  gaps               integer,
  error              text,
  created_at         timestamptz not null default now(),
  completed_at       timestamptz
);

create index if not exists content_gap_runs_client_idx
  on content_gap_runs (client_id, created_at desc);

alter table content_gap_runs enable row level security;

-- ---------------------------------------------------------------------------
-- Keyword × page results (child of a run)
-- ---------------------------------------------------------------------------
create table if not exists content_gap_keywords (
  id                 uuid primary key default gen_random_uuid(),
  run_id             uuid not null references content_gap_runs (id) on delete cascade,
  client_id          uuid not null references clients (id) on delete cascade,
  keyword            text not null,
  page_url           text,           -- the client money-page mapped to this keyword
  -- SERP state
  client_position    integer,        -- null = client absent from the top-N organic
  aio_present         boolean,
  in_aio             boolean,        -- client cited in the AIO (only meaningful when aio_present)
  verdict            text not null
                       check (verdict in ('win', 'aio_gap', 'organic_gap', 'full_gap')),
  -- the resolved competitor set for this keyword's gap (jsonb array)
  competitors        jsonb,
  -- per-dimension gap payload (authority / traffic / entity / etc.)
  gap                jsonb,
  -- the competitor-anchored on-page diff (build_onpage_diff output)
  onpage_diff        jsonb,
  -- provenance: which serp_snapshot this keyword read from, or a fresh capture
  serp_snapshot_id   uuid references serp_snapshots (id) on delete set null,
  captured_fresh     boolean not null default false,
  created_at         timestamptz not null default now()
);

create index if not exists content_gap_keywords_run_idx
  on content_gap_keywords (run_id);
create index if not exists content_gap_keywords_client_idx
  on content_gap_keywords (client_id, created_at desc);

alter table content_gap_keywords enable row level security;

-- ---------------------------------------------------------------------------
-- Daily paid-call budget meter + atomic reservation (mirrors domain_intel_usage)
-- ---------------------------------------------------------------------------
create table if not exists content_gap_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table content_gap_usage enable row level security;

create or replace function reserve_content_gap_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into content_gap_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update content_gap_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;

-- ---------------------------------------------------------------------------
-- async_jobs job_type CHECK — REBUILT from the LIVE constraint (per the standing
-- migration rule; do not trust a repo migration file) + 'content_gap_scan'.
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
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
    'social_fanout', 'coverage_audit', 'google_trends_scan', 'paa_manifest_qa',
    'brand_guide_spike', 'brand_guide_generate', 'brand_guide_render',
    'content_gap_scan'
  ])
);
