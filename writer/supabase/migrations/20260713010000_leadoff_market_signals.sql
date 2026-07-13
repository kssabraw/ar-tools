-- Increment 2 of score enrichment: precomputed winnability signals per market
-- so the BOARD grade can use proximity + footprint (not just permits) without
-- computing octant math for every row on each page load. App-owned; populated
-- by the leadoff_signal_refresh job (pure math on already-captured pins +
-- footprint caches, $0). proximity_opportunity is board-wide (needs only the
-- geocoded pins); site/brand pressure fill where a scout has run.
create table if not exists public.leadoff_market_signals (
  city_id bigint not null,
  category_id text not null,
  proximity_opportunity double precision,
  site_pressure double precision,
  brand_pressure double precision,
  pins integer,
  computed_at timestamptz not null default now(),
  primary key (city_id, category_id)
);
alter table public.leadoff_market_signals enable row level security;

-- widen the async_jobs job_type CHECK for the refresh job
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;
alter table public.async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array['website_scrape','page_structure_scrape','silo_dedup','gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report','serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan','rank_location_derive','brand_scan','brand_report','notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp','review_intel','backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item','freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze','internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot','content_batch_item','task_month_generate','task_due_sweep','task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap','link_gap','leadoff_permits','leadoff_geocode','qa_review','leadoff_signal_refresh']::text[]));
