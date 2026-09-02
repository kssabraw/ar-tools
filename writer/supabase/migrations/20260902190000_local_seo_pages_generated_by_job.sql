-- local_seo_pages.generated_by_job_id — the async job that produced the page.
--
-- The job handlers (local_seo_generate / local_seo_reoptimize_url /
-- local_seo_reoptimize_page) look this up FIRST on every attempt. Since 2026-09-02
-- a transient failure re-queues the job instead of failing it terminally; if
-- that failure lands AFTER the page was persisted (the completion write to
-- async_jobs raising a transport error, or the stale-job reaper requeueing a
-- row whose page had already landed), the retry resumes with the existing page
-- instead of generating — and paying for — a duplicate.
alter table local_seo_pages
  add column if not exists generated_by_job_id uuid;

create index if not exists idx_local_seo_pages_generated_by_job
  on local_seo_pages (generated_by_job_id)
  where generated_by_job_id is not null;
