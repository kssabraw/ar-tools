-- Fanout content scheduler: bounded retry for transient generation failures.
--
-- Add a per-run `attempts` counter so a run that fails on a transient error
-- (LLM overload / 529, research timeout, a DataForSEO hiccup, a worker restart
-- mid-generation) is requeued with backoff instead of being permanently marked
-- `failed`. The scheduler reads/increments this on each failure; when it reaches
-- `scheduler_max_attempts` the run is dead-lettered (failed + a notification).
--
-- Additive + backfilled to 0, so existing rows and the `claim_scheduled_runs`
-- RPC (which returns SETOF this table) keep working unchanged.
alter table fanout.scheduled_article_runs
  add column if not exists attempts integer not null default 0;

comment on column fanout.scheduled_article_runs.attempts is
  'Number of generation attempts made for this run. Incremented on each failure; '
  'at scheduler_max_attempts the run is dead-lettered (status=failed + notification). '
  'Reset to 0 by a manual retry.';
