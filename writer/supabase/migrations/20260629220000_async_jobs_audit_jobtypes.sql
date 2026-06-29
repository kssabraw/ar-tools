-- ============================================================
-- async_jobs.job_type — final UNION of main's list + the audit job types
-- ============================================================
-- This migration is timestamped AFTER main's latest job_type redefinition
-- (20260629210000_local_relevance_scores) so it is the last word regardless of
-- migration ordering after the managed-engagement branch merges. It adds the
-- three audit job types (site_audit / backlink_audit / citation_audit) to main's
-- full deployed list. (The live DB was set to this same union directly.)
-- ============================================================

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
    'site_audit', 'backlink_audit', 'citation_audit'
  ]));
