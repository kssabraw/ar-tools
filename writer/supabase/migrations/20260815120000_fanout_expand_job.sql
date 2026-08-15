-- Durable Fanout expansion (issue #686, Phase 1).
--
-- The Fanout keyword pipeline runs in a per-process ThreadPoolExecutor with the
-- session's status as its only claim, so a platform-api restart (every deploy)
-- kills an in-flight expansion and strands / errors the run. Phase 1 moves the
-- expensive `expand` step onto the durable `async_jobs` queue so the shared
-- worker's graceful-shutdown drain + stale-job reaper recover it automatically.
--
-- This adds the `fanout_expand` job type. The live CHECK is wider than any single
-- repo migration, so — per the established pattern — reproduce the full current
-- set and append the new value.
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup',
    'gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market',
    'gsc_research','rank_report','serp_snapshot','maps_scan','maps_report','local_seo_silo',
    'local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page',
    'service_page_plan','rank_location_derive','brand_scan','brand_report',
    'notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly',
    'competitor_gbp','review_intel','backlink_intel','content_intel','local_relevance',
    'syndication_scan','syndication_item','freeze_check','citation_check',
    'page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan',
    'icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze',
    'internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot',
    'content_batch_item','task_month_generate','task_due_sweep','task_import_asana',
    'leadoff_tryout','leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap',
    'link_gap','leadoff_permits','leadoff_geocode','qa_review','leadoff_signal_refresh',
    'leadoff_city_finder','leadoff_income_backfill','leadoff_county_backfill',
    'keyword_research','ecommerce_generate','ecommerce_reoptimize_url','ecommerce_action',
    'github_infer_patterns','illustrate_run','blog_github_publish','gbp_post_publish',
    'gbp_post_generate','gbp_posts_sync','site_inventory','website_provision',
    'website_theme_compile','website_core_pages','website_page_publish',
    'website_deploy_poll','website_page_generate','deliverables_sheet_provision',
    'deliverables_log','deliverable_notes_scan','service_page_score','service_page_reoptimize',
    'keyword_topic_research','keyword_research_report','backlink_lookup','fanout_report',
    'blog_score','blog_reoptimize',
    'fanout_expand'
  ])
);
