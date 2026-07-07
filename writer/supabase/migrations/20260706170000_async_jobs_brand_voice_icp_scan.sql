-- Migration: 20260706170000_async_jobs_brand_voice_icp_scan.sql
-- Purpose: Allow the two new async job types that auto-generate a new client's
--          brand voice + ICP at creation time (services/brand_voice_service.py
--          run_brand_voice_scan_job, services/icp_service.py run_icp_scan_job,
--          enqueued by routers/clients.py). Strictly additive — no previously
--          allowed value is removed. Distinct from the existing AI-Visibility
--          'brand_scan'.

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
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp', 'review_intel',
    'backlink_intel', 'content_intel', 'local_relevance',
    'syndication_scan', 'syndication_item',
    'freeze_check', 'citation_check', 'page_backlink_intel',
    'strategy_review',
    'brand_voice_scan', 'icp_scan'
  ]));
