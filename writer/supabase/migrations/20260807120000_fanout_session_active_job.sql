-- Which pipeline job holds a session's run claim (kind + its replayable args,
-- e.g. {"kind":"plan","direct":false,"resumes":0}). Written by fanout/jobs.py's
-- submit_* at claim time and overwritten by every subsequent submit, so for a
-- session stuck in a live status it always describes the interrupted job.
-- Read by fanout/run_recovery.py to decide whether an interrupted run can
-- auto-resume: a killed article-planning run restarts planning automatically
-- (expansion's keywords are durable, planning is replayable); anything else
-- keeps the manual recovery path. `resume_pending: true` marks a recovered
-- session the startup executor should re-plan.
alter table fanout.sessions add column if not exists active_job jsonb;
