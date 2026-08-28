-- Live progress for long-running background jobs (generate / reoptimize).
-- The nlp worker emits per-stage SSE progress events; the job runner writes the
-- latest onto these columns so the frontend's jobs/status poll can render a
-- moving bar + current stage instead of a frozen segment. Both nullable and
-- additive — every other job type simply leaves them null.
ALTER TABLE async_jobs
  ADD COLUMN IF NOT EXISTS progress smallint,
  ADD COLUMN IF NOT EXISTS progress_message text;
