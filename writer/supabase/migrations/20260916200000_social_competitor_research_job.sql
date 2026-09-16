-- Social Media P1 — competitor research (analyze-in-place, Apify-only; ADR-0002).
-- Adds the `social_competitor_research` async job type: one job per client scrapes
-- its competitors' public per-platform handles (social_competitor_handles) via Apify,
-- rolls the public post/engagement/caption data up into social_competitor_signals
-- (both tables already exist from 20260905120000). No new tables here.
--
-- The CHECK is rebuilt from the LIVE constraint (which is wider than any single
-- repo migration file) so this never narrows the allowed set.

alter table async_jobs drop constraint if exists async_jobs_job_type_check;

alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup',
    'gsc_ingest','gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market',
    'gsc_research','rank_report','serp_snapshot','maps_scan','maps_report','local_seo_silo',
    'local_seo_generate','local_seo_reoptimize_url','local_seo_reoptimize_page','service_page_plan',
    'rank_location_derive','brand_scan','brand_report','notification_dispatch','reopt_plan',
    'client_report','maps_analyze','asana_monthly','competitor_gbp','review_intel','backlink_intel',
    'content_intel','local_relevance','syndication_scan','syndication_item','freeze_check',
    'citation_check','page_backlink_intel','strategy_review','maps_image_backfill','brand_voice_scan',
    'icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze',
    'internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot',
    'content_batch_item','task_month_generate','task_due_sweep','task_import_asana','leadoff_tryout',
    'leadoff_scout','leadoff_ai_probe','domain_overview','keyword_gap','link_gap','leadoff_permits',
    'leadoff_geocode','qa_review','leadoff_signal_refresh','leadoff_city_finder','leadoff_income_backfill',
    'leadoff_county_backfill','keyword_research','ecommerce_generate','ecommerce_reoptimize_url',
    'ecommerce_action','github_infer_patterns','illustrate_run','blog_github_publish','gbp_post_publish',
    'gbp_post_generate','gbp_posts_sync','site_inventory','website_provision','website_theme_compile',
    'website_core_pages','website_page_publish','website_deploy_poll','website_page_generate',
    'deliverables_sheet_provision','deliverables_log','deliverable_notes_scan','service_page_score',
    'service_page_reoptimize','keyword_topic_research','keyword_research_report','backlink_lookup',
    'fanout_report','blog_score','blog_reoptimize','fanout_expand','gbp_onboard','gbp_search_keywords',
    'fanout_plan','fanout_regate','fanout_fanout','fanout_architecture','ga4_ingest','gbp_reviews',
    'leadoff_map_refresh','leadoff_placement','leadoff_zip_demand','voice_revalidate','autonomy_run',
    'score_external','everhour_mirror','everhour_sync','plan_handoff','local_seo_matrix_suggest',
    'local_seo_matrix_publish','guide_sync','gbp_profile_apply','gbp_profile_draft','gbp_profile_sync',
    'gbp_profile_monitor','social_publish','social_fanout','social_profile_provision','coverage_audit',
    'google_trends_scan','paa_manifest_qa','brand_guide_spike','brand_guide_generate','brand_guide_render',
    'content_gap_scan','social_competitor_research'
  ])
);
