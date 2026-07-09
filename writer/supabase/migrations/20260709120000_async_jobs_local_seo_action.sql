-- Migration: 20260709120000_async_jobs_local_seo_action.sql
-- Purpose: Allow the new `local_seo_action` async job type. The Local SEO
--          interactive actions (precheck / analyze / find-page / score /
--          related-pages / social-posts) were heartbeat-SSE streams that died
--          from the user's view when they navigated away. They now run as a
--          backgrounded `local_seo_action` job (services/local_seo_service.py
--          run_local_seo_action_job) whose result is stored on the job row and
--          polled via .../jobs/status, so the work completes and the result is
--          retrievable after navigating away. Strictly additive — no
--          previously-allowed value is removed.

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
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
    'rank_keyword_report', 'local_seo_action'
  ]));
