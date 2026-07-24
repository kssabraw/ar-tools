-- Idempotency + recovery-ownership key for externally-driven runs.
--
-- Scheduled content (content-batch items, fanout scheduled service-page runs)
-- drives the orchestrator from a job/row that has its OWN restart recovery
-- (drain+reclaim / the fanout scheduler sweep). But `runs` ALSO has startup
-- recovery (recover_stuck_runs). When a redeploy lands mid-generation both fire:
-- the job re-runs create_run_and_snapshot (a NEW run) while recover_stuck_runs
-- resumes the orphaned one → two runs → duplicate published articles.
--
-- source_ref is the work-item key (e.g. 'batch_item:<id>', 'fanout_run:<id>').
-- create_run_and_snapshot reuses a non-terminal/complete run for the same key
-- instead of creating a second, and recover_stuck_runs SKIPS runs that carry one
-- (their owning job/row is the single recovery vehicle). Interactive runs (API,
-- resume, rerun) leave it null and are unaffected.

alter table runs
    add column if not exists source_ref text;

-- Fast lookup for the get-or-create dedupe + the recovery skip.
create index if not exists idx_runs_source_ref
    on runs (source_ref)
    where source_ref is not null;
