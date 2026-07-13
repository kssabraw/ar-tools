-- Migration: 20260713040000_keyword_research.sql
-- Purpose: Keyword Research module (the seed-keyword explorer). Enter seed
--   keyword(s) for a client → the DataForSEO Labs keyword_ideas endpoint returns
--   the related keyword universe (each idea enriched with volume / CPC /
--   competition / KD / intent in one billed call) → auto-clustered into topic
--   groups → persisted as a run so the view is a cheap re-read and CSV export is
--   deterministic. This is a research tool, NOT a content generator — it backs
--   the "Keyword Research" workspace card (which used to point at the Topic
--   Fanout mass-content pipeline; the Fanout stays behind "Create Mass Posts").
--
--   * keyword_research_runs      — one row per run (seed set + rollup counts)
--   * keyword_research_keywords  — child: every idea + its cluster label
--   * keyword_research_usage     — per-day paid-call meter (mirrors domain_intel_usage)
--   * reserve_keyword_research_calls() — atomic check-and-increment
--
--   Also widens async_jobs.job_type to add 'keyword_research'. The array below
--   is the FULL live constraint set (wider than any single repo migration file)
--   plus the new type, so applying this never drops a live-only job type.
--
-- All tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).

-- ---------------------------------------------------------------------------
-- Runs (one per research run)
-- ---------------------------------------------------------------------------
create table if not exists keyword_research_runs (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  seeds          text[] not null default '{}',
  location_code  integer,
  language_code  text default 'en',
  keyword_count  integer not null default 0,
  cluster_count  integer not null default 0,
  status         text not null default 'complete',
  cost_usd       numeric,
  created_at     timestamptz not null default now()
);

create index if not exists keyword_research_runs_client_idx
  on keyword_research_runs (client_id, created_at desc);

alter table keyword_research_runs enable row level security;

-- ---------------------------------------------------------------------------
-- Keywords (child of a run) — the explorer table + cluster membership
-- ---------------------------------------------------------------------------
create table if not exists keyword_research_keywords (
  id                 uuid primary key default gen_random_uuid(),
  run_id             uuid not null references keyword_research_runs (id) on delete cascade,
  keyword            text not null,
  cluster_label      text,
  volume             integer,
  cpc_usd            numeric,
  competition_index  numeric,
  keyword_difficulty numeric,
  search_intent      text,
  is_question        boolean not null default false,
  opportunity_score  numeric
);

create index if not exists keyword_research_keywords_run_idx
  on keyword_research_keywords (run_id);

alter table keyword_research_keywords enable row level security;

-- ---------------------------------------------------------------------------
-- Daily paid-call budget meter + atomic reservation (mirrors domain_intel_usage)
-- ---------------------------------------------------------------------------
create table if not exists keyword_research_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table keyword_research_usage enable row level security;

create or replace function reserve_keyword_research_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into keyword_research_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update keyword_research_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;

-- ---------------------------------------------------------------------------
-- async_jobs job_type — add 'keyword_research' (full live set preserved)
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
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
    'keyword_research'
  ])
);
