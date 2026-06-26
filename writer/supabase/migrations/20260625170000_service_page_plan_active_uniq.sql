-- One active service_page_plan job per client. Closes the reuse-then-insert race
-- in start_service_plan: a double-click (or two tabs) could pass the "is there a
-- pending/running plan?" check simultaneously and insert two jobs, each billing a
-- full Fanout (DataForSEO + LLM) run. This partial unique index lets the DB reject
-- the second insert; the service catches the violation and returns the winner.
--
-- Scoped to job_type='service_page_plan' so it does not constrain any other async
-- job type.

create unique index if not exists async_jobs_service_page_plan_active_uniq
  on async_jobs (entity_id)
  where job_type = 'service_page_plan' and status in ('pending', 'running');
