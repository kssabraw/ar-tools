-- Social P4 (Phase A) foundations — applied live 2026-09-19.
--
-- 1. autonomy_runs.domain: the Social Manager orchestrator (P4) writes its runs to the
--    SAME autonomy_runs ledger as the SEO executor so DORA's prov_autonomy (which reads
--    autonomy_runs) sees social runs without a second table. A discriminator column lets
--    DORA split SEO vs social. Additive + defaulted 'seo', so every existing row reads
--    'seo' and no single-domain reader breaks.
-- 2. async_jobs 'social_autonomy_run' job type — the loop's async job. CHECK rebuilt
--    from the LIVE constraint (suite rule) with the one new type appended.

alter table autonomy_runs add column if not exists domain text not null default 'seo';

alter table async_jobs drop constraint if exists async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape'::text, 'page_structure_scrape'::text, 'page_structure_parse'::text,
    'silo_dedup'::text, 'gsc_ingest'::text, 'gsc_page_ingest'::text, 'gsc_materialize'::text,
    'dataforseo_rank'::text, 'keyword_market'::text, 'gsc_research'::text, 'rank_report'::text,
    'serp_snapshot'::text, 'maps_scan'::text, 'maps_report'::text, 'local_seo_silo'::text,
    'local_seo_generate'::text, 'local_seo_reoptimize_url'::text, 'local_seo_reoptimize_page'::text,
    'service_page_plan'::text, 'rank_location_derive'::text, 'brand_scan'::text, 'brand_report'::text,
    'notification_dispatch'::text, 'reopt_plan'::text, 'client_report'::text, 'maps_analyze'::text,
    'asana_monthly'::text, 'competitor_gbp'::text, 'review_intel'::text, 'backlink_intel'::text,
    'content_intel'::text, 'local_relevance'::text, 'syndication_scan'::text, 'syndication_item'::text,
    'freeze_check'::text, 'citation_check'::text, 'page_backlink_intel'::text, 'strategy_review'::text,
    'maps_image_backfill'::text, 'brand_voice_scan'::text, 'icp_scan'::text, 'asana_push'::text,
    'competitor_intel'::text, 'gbp_metrics_ingest'::text, 'internal_link_analyze'::text,
    'internal_link_apply'::text, 'rank_keyword_report'::text, 'local_seo_action'::text,
    'backlink_snapshot'::text, 'content_batch_item'::text, 'task_month_generate'::text,
    'task_due_sweep'::text, 'task_import_asana'::text, 'leadoff_tryout'::text, 'leadoff_scout'::text,
    'leadoff_ai_probe'::text, 'domain_overview'::text, 'keyword_gap'::text, 'link_gap'::text,
    'leadoff_permits'::text, 'leadoff_geocode'::text, 'qa_review'::text, 'leadoff_signal_refresh'::text,
    'leadoff_city_finder'::text, 'leadoff_income_backfill'::text, 'leadoff_county_backfill'::text,
    'keyword_research'::text, 'ecommerce_generate'::text, 'ecommerce_reoptimize_url'::text,
    'ecommerce_action'::text, 'github_infer_patterns'::text, 'illustrate_run'::text,
    'blog_github_publish'::text, 'gbp_post_publish'::text, 'gbp_post_generate'::text,
    'gbp_posts_sync'::text, 'site_inventory'::text, 'website_provision'::text,
    'website_theme_compile'::text, 'website_core_pages'::text, 'website_page_publish'::text,
    'website_deploy_poll'::text, 'website_page_generate'::text, 'deliverables_sheet_provision'::text,
    'deliverables_log'::text, 'deliverable_notes_scan'::text, 'service_page_score'::text,
    'service_page_reoptimize'::text, 'keyword_topic_research'::text, 'keyword_research_report'::text,
    'backlink_lookup'::text, 'fanout_report'::text, 'blog_score'::text, 'blog_reoptimize'::text,
    'fanout_expand'::text, 'gbp_onboard'::text, 'gbp_search_keywords'::text, 'fanout_plan'::text,
    'fanout_regate'::text, 'fanout_fanout'::text, 'fanout_architecture'::text, 'ga4_ingest'::text,
    'gbp_reviews'::text, 'leadoff_map_refresh'::text, 'leadoff_placement'::text,
    'leadoff_zip_demand'::text, 'voice_revalidate'::text, 'autonomy_run'::text, 'score_external'::text,
    'everhour_mirror'::text, 'everhour_sync'::text, 'plan_handoff'::text,
    'local_seo_matrix_suggest'::text, 'local_seo_matrix_publish'::text, 'guide_sync'::text,
    'gbp_profile_apply'::text, 'gbp_profile_draft'::text, 'gbp_profile_sync'::text,
    'gbp_profile_monitor'::text, 'social_publish'::text, 'social_fanout'::text,
    'social_profile_provision'::text, 'coverage_audit'::text, 'google_trends_scan'::text,
    'paa_manifest_qa'::text, 'brand_guide_spike'::text, 'brand_guide_generate'::text,
    'brand_guide_render'::text, 'content_gap_scan'::text, 'social_competitor_research'::text,
    'leadoff_grade'::text, 'leadoff_grade_all'::text,
    'social_autonomy_run'::text
  ])
);
