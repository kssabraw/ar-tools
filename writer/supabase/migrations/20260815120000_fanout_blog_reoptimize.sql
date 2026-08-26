-- Fanout blog reoptimization.
--
-- A client-linked Fan-out blog article is mirrored into the suite as a
-- first-class blog `run` (fanout.article_outputs.suite_run_id). Reoptimizing a
-- Fan-out article = score + rewrite-to-threshold that suite run (the same blog
-- score/reopt spine used by the Runs tool), then REFLECT the improved article
-- back onto a fresh fanout.article_outputs row so the Fan-out Articles library
-- shows it. Two dedicated async_jobs types drive this (fanout-specific
-- orchestration: fanout_blog_score = observation, fanout_blog_reoptimize =
-- output / freeze-gated).

-- 1) async_jobs.job_type allowlist — add the two Fan-out reopt job types.
-- Reconstructed from the live constraint (2026-08-15) so nothing is dropped.
alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type in (
    'website_scrape', 'page_structure_scrape', 'page_structure_parse', 'silo_dedup',
    'gsc_ingest', 'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive', 'brand_scan',
    'brand_report', 'notification_dispatch', 'reopt_plan', 'client_report', 'maps_analyze',
    'asana_monthly', 'competitor_gbp', 'review_intel', 'backlink_intel', 'content_intel',
    'local_relevance', 'syndication_scan', 'syndication_item', 'freeze_check',
    'citation_check', 'page_backlink_intel', 'strategy_review', 'maps_image_backfill',
    'brand_voice_scan', 'icp_scan', 'asana_push', 'competitor_intel', 'gbp_metrics_ingest',
    'internal_link_analyze', 'internal_link_apply', 'rank_keyword_report', 'local_seo_action',
    'backlink_snapshot', 'content_batch_item', 'task_month_generate', 'task_due_sweep',
    'task_import_asana', 'leadoff_tryout', 'leadoff_scout', 'leadoff_ai_probe',
    'domain_overview', 'keyword_gap', 'link_gap', 'leadoff_permits', 'leadoff_geocode',
    'qa_review', 'leadoff_signal_refresh', 'leadoff_city_finder', 'leadoff_income_backfill',
    'leadoff_county_backfill', 'keyword_research', 'ecommerce_generate',
    'ecommerce_reoptimize_url', 'ecommerce_action', 'github_infer_patterns', 'illustrate_run',
    'blog_github_publish', 'gbp_post_publish', 'gbp_post_generate', 'gbp_posts_sync',
    'site_inventory', 'website_provision', 'website_theme_compile', 'website_core_pages',
    'website_page_publish', 'website_deploy_poll', 'website_page_generate',
    'deliverables_sheet_provision', 'deliverables_log', 'deliverable_notes_scan',
    'service_page_score', 'service_page_reoptimize', 'keyword_topic_research',
    'keyword_research_report', 'backlink_lookup', 'fanout_report', 'blog_score',
    'blog_reoptimize', 'wheelhouse_generate',
    -- Fan-out blog reoptimization:
    'fanout_blog_score', 'fanout_blog_reoptimize'
  )
);

-- 2) Persist the latest blog composite score on the Fan-out article so the
-- Articles library can show a score badge across reloads (the reflected reopt
-- row carries the improved score; a score-only run updates the latest row).
alter table fanout.article_outputs add column if not exists composite_score numeric;
alter table fanout.article_outputs add column if not exists composite_status text;
