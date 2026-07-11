-- Auto-resume for blog/service-page runs orphaned by a service restart.
-- orchestrate_run executes as an in-process background task, so a redeploy or
-- crash mid-run used to strand the run and startup recovery marked it failed
-- ("Service restarted mid-run. Please re-run."). Recovery now RE-DISPATCHES the
-- run instead — the orchestrator already skips completed module_outputs, so a
-- resume only re-runs the interrupted stage. resume_count counts those
-- auto-resumes so a run that keeps dying (e.g. one that crashes the service)
-- fails permanently after `run_auto_resume_max` attempts instead of
-- crash-looping forever.
alter table runs add column if not exists resume_count integer not null default 0;
