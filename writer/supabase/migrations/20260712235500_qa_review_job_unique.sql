-- Migration: 20260712235500_qa_review_job_unique.sql
-- Purpose: make qa_review enqueue race-safe (adversarial review 2026-07-12).
--          enqueue_qa_review's scan-then-insert had a TOCTOU window: two
--          near-simultaneous In-QA transitions for the same task could both
--          pass the scan and double-insert. The DB becomes the arbiter — one
--          LIVE (pending/running) qa_review job per task (entity_id carries
--          the task id on these rows); completed/failed rows leave the index,
--          so later re-reviews are unaffected. Safe to add now: the feature
--          is dormant and no qa_review rows exist yet.
create unique index if not exists idx_async_jobs_qa_review_live
  on async_jobs (entity_id)
  where job_type = 'qa_review' and status in ('pending', 'running');
