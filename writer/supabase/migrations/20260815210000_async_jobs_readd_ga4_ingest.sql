-- Re-add 'ga4_ingest' to the async_jobs job_type CHECK.
--
-- 20260815130000_ga4_reporting added 'ga4_ingest', but two CHECK-recreating
-- migrations that landed just after it — 20260815170000_gbp_onboard_job and
-- 20260815190000_fanout_pipeline_durable_jobs — each rebuilt the CHECK from a
-- snapshot that predated the GA4 migration and so dropped 'ga4_ingest'. On the
-- live database this left the constraint WITHOUT 'ga4_ingest' (verified
-- 2026-08-15 via an end-to-end ingest test: the job insert failed the CHECK),
-- which would break every GA4 ingest the moment a property connects.
--
-- This migration is the authoritative last word: it recreates the CHECK from
-- the full current live set and includes 'ga4_ingest'. Applied live the same
-- day (migration name async_jobs_readd_ga4_ingest). Any future migration that
-- rebuilds this CHECK MUST read the live constraint (not repo history) and keep
-- every value — see the note in 20260807130000_async_jobs_service_page_score.
alter table public.async_jobs drop constraint if exists async_jobs_job_type_check;
alter table public.async_jobs add constraint async_jobs_job_type_check check (
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
    'fanout_plan', 'fanout_regate', 'fanout_fanout', 'fanout_architecture',
    'gbp_reviews', 'ga4_ingest'
  )
);
