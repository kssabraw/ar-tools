-- Peer-cohort field-strength signal: judge a market's GBP competitive field
-- against COMPARABLE cities (similar size + household income, same category)
-- rather than in absolute terms. Two pieces:
--   1. public.city_household_income — per-city median household income from the
--      free Census ACS 5-year API (table B19013), backfilled by the
--      leadoff_income_backfill job. App-owned; one row per board city.
--   2. leadoff_market_signals gains the precomputed peer_field signal (+ the
--      cohort median/size it was measured against, for UI transparency),
--      alongside the existing proximity/site/brand winnability signals.

create table if not exists public.city_household_income (
  city_id bigint primary key,
  state_code text,
  median_household_income bigint,
  matched_name text,
  source text not null default 'census_acs5',
  pulled_at timestamptz not null default now()
);
alter table public.city_household_income enable row level security;

alter table public.leadoff_market_signals
  add column if not exists peer_field double precision,
  add column if not exists peer_cohort_median double precision,
  add column if not exists peer_cohort_n integer;

-- widen the async_jobs job_type CHECK for the income backfill job
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;
alter table public.async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array['website_scrape','page_structure_scrape','silo_dedup','gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report','serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan','rank_location_derive','brand_scan','brand_report','notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp','review_intel','backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item','freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze','internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot','content_batch_item','task_month_generate','task_due_sweep','task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap','link_gap','leadoff_permits','leadoff_geocode','qa_review','leadoff_signal_refresh','leadoff_city_finder','leadoff_income_backfill']::text[]));
