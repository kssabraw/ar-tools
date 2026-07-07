-- Migration: 20260707020000_asana_push.sql
-- Purpose: Asana task push — Recipe Engine plans + approved strategist
--          proposals become real Asana tasks (Recipe Engine v1 follow-up +
--          Strategist Phase 5).
--   * monthly_task_plans.asana_push — per-line {key: {gid, url, name}} map of
--     created tasks; the idempotency ledger for re-pushes (a partial failure
--     re-push creates only the missing lines).
--   * async_jobs.job_type gains 'asana_push' (the push runs as an async job so
--     the Task Plan UI polls instead of blocking on N Asana calls).
-- Strategist proposals store their task {gid, url} inside the existing
-- strategy_reviews.proposals JSONB — no new column needed.

alter table monthly_task_plans add column if not exists asana_push jsonb;

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
    'brand_voice_scan', 'icp_scan',
    'asana_push'
  ]));
