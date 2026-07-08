-- Fanout: visible queue state for pipeline runs.
--
-- The pipeline worker pool caps concurrent runs (2/process), but the run claim
-- set status='running' at submit time — so a run waiting for a worker slot was
-- indistinguishable from an executing one (same spinner, same fake progress
-- bar). Endpoints now claim runs as 'queued'; the worker flips the claim to
-- 'running' when it actually picks the job up (jobs._claims_start ->
-- store.try_mark_started).
alter type fanout.session_status add value if not exists 'queued' before 'running';
