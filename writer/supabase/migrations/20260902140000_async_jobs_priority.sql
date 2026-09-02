-- async_jobs.priority — a real queue priority, replacing the decaying
-- `scheduled_at` stagger as the way bulk work yields to interactive work.
--
-- Bulk flows (Local SEO / Ecommerce / Wheelhouse bulk-create, matrix runs)
-- enqueue one job per item stamped 3 minutes apart, on the theory that a
-- now-dated interactive job would then sort ahead of the rest of the batch.
-- A page generation takes 10–12 minutes across two lanes, so the batch drains
-- slower than its timestamps advance: after ~7 jobs every remaining bulk
-- timestamp is in the past and anything clicked from then on queues behind
-- the whole batch (a page-structure scrape sat behind 32 generations on
-- 2026-09-02). Ordering the claim by priority DESC first, then scheduled_at,
-- makes an interactive job (0) beat a background job (-1) regardless of age.
alter table async_jobs
  add column if not exists priority smallint not null default 0;

-- The claim scans the oldest pending rows by (priority desc, scheduled_at).
create index if not exists idx_async_jobs_pending_priority
  on async_jobs (priority desc, scheduled_at)
  where status = 'pending';
