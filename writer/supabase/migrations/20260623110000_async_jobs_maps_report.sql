-- Allow the 'maps_report' async job (Maps Local Rank Analysis report generation).
-- Without this, enqueue silently fails the async_jobs job_type CHECK constraint
-- and reports never generate.
alter table public.async_jobs
  drop constraint if exists async_jobs_job_type_check;

alter table public.async_jobs
  add constraint async_jobs_job_type_check check (
    job_type = any (array[
      'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
      'serp_snapshot', 'maps_scan', 'maps_report'
    ])
  );
