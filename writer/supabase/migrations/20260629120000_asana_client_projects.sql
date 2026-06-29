-- Migration: 20260629120000_asana_client_projects.sql
-- Purpose: Asana task integration (docs/modules/asana-task-integration-plan-v1_0.md).
--          Maps each AR Tools client to its Asana project, so the monthly
--          section-automation job knows where to clone the "Template" section
--          forward. Everything else the integration needs lives in Asana itself
--          (the template tasks, assignees, custom fields) or in config (the
--          team list + custom-field GIDs), so this is the only new table.
--
--          One row per client (client_id is the PK → enforces uniqueness).
--          Populated once per client at onboarding.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

create table if not exists asana_client_projects (
  client_id   uuid primary key references clients(id) on delete cascade,
  project_gid text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table asana_client_projects enable row level security;
