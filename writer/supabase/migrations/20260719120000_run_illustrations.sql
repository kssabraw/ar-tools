-- Per-run illustration plan + generated visual assets (hero + inline body
-- images/charts). Additive: the illustration layer never mutates the canonical
-- sources_cited article; the publish render path interleaves these by anchor.
alter table runs add column if not exists illustrations jsonb;

-- New async job that generates a run's illustrations (image briefs -> gpt-image-1
-- -> public bucket; chart series extraction -> deterministic inline SVG).
-- The live CHECK is wider than any single repo migration file; this preserves
-- the full live set and adds 'illustrate_run'.
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','silo_dedup','gsc_ingest','gsc_page_ingest',
    'gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report',
    'serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate',
    'local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan',
    'rank_location_derive','brand_scan','brand_report','notification_dispatch','reopt_plan',
    'client_report','maps_analyze','asana_monthly','competitor_gbp','review_intel',
    'backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item',
    'freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill',
    'brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest',
    'internal_link_analyze','internal_link_apply','rank_keyword_report','local_seo_action',
    'backlink_snapshot','content_batch_item','task_month_generate','task_due_sweep',
    'task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview',
    'keyword_gap','link_gap','leadoff_permits','leadoff_geocode','qa_review',
    'leadoff_signal_refresh','leadoff_city_finder','leadoff_income_backfill','leadoff_county_backfill',
    'keyword_research','ecommerce_generate','ecommerce_reoptimize_url','ecommerce_action',
    'github_infer_patterns','illustrate_run'
  ])
);
