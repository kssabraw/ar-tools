-- Run-level transient-failure auto-retry (resilience layer).
--
-- When a run fails at a stage because a transient upstream outage (e.g. a
-- multi-minute DataForSEO SERP outage) outlasted the in-call HTTP retries, the
-- orchestrator now parks it in the new `retry_scheduled` status and the shared
-- scheduler re-dispatches it after a backoff delay, instead of leaving it
-- terminally failed for a human to notice and re-run. Bounded by
-- `run_transient_retry_max`; permanent failures still fail immediately.
--
--   retry_count  — number of automatic transient-retries already attempted
--                  (distinct from resume_count, which counts orphaned-run
--                  recoveries after a process restart).
--   next_retry_at — when the scheduler should re-dispatch a retry_scheduled run.

alter table runs
    add column if not exists retry_count integer not null default 0,
    add column if not exists next_retry_at timestamptz;

-- Partial index for the scheduler's per-tick due-check.
create index if not exists idx_runs_retry_due
    on runs (next_retry_at)
    where status = 'retry_scheduled';

-- Allow the new non-terminal status.
alter table runs drop constraint if exists runs_status_check;
alter table runs add constraint runs_status_check check (
    status = any (array[
        'queued',
        'brief_running',
        'sie_running',
        'research_running',
        'writer_running',
        'sources_cited_running',
        'service_brief_running',
        'service_writer_running',
        'service_scoring_running',
        'service_reopt_running',
        'retry_scheduled',
        'complete',
        'failed',
        'cancelled'
    ])
);
