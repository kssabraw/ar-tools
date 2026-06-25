-- Allow the `service_page_plan` async job: the Fanout-powered service-page
-- completeness planner (mirrors `local_seo_silo`, seeded by the business
-- category) runs as an async_jobs job. Extend the job_type allowlist.

alter table async_jobs
  drop constraint async_jobs_job_type_check;

alter table async_jobs
  add constraint async_jobs_job_type_check check (
    job_type = any (array[
      'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
      'serp_snapshot', 'maps_scan', 'maps_report', 'page_structure_scrape',
      'local_seo_silo', 'gsc_research', 'service_page_plan'
    ])
  );
