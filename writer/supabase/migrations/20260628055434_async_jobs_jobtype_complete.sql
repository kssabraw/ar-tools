-- Migration: 20260628055434_async_jobs_jobtype_complete.sql
-- Purpose: Align async_jobs.job_type with the job types the worker actually
--          dispatches (services/job_worker.py). The enum had drifted —
--          local_seo_generate, local_seo_reoptimize_url, local_seo_reoptimize_page,
--          brand_scan, brand_report were dispatched by the worker but absent from
--          the CHECK, so enqueuing any of them would raise a constraint violation
--          (none had been enqueued yet, so it was latent). Strictly additive —
--          no previously-allowed value is removed.

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch'
  ]));
