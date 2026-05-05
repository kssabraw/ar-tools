-- Migration: 20260430120200_indexes.sql
-- Purpose: Indexes for common query patterns

-- clients: filter and sort by archived status, search by name
create index idx_clients_archived  on clients (archived);
create index idx_clients_name      on clients (name);

-- runs: heavy querying by client, status, recency, creator
create index idx_runs_client_id    on runs (client_id);
create index idx_runs_status       on runs (status);
create index idx_runs_created_at   on runs (created_at desc);
create index idx_runs_created_by   on runs (created_by);

-- module_outputs: lookup by run_id is the dominant query
create index idx_module_outputs_run_id on module_outputs (run_id);

-- async_jobs: worker polls by status + scheduled_at
create index idx_async_jobs_status       on async_jobs (status);
create index idx_async_jobs_scheduled_at on async_jobs (scheduled_at);
