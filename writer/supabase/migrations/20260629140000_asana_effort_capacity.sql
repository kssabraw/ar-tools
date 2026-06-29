-- Migration: 20260629140000_asana_effort_capacity.sql
-- Purpose: Asana Team Workload — effort-weighting (Phase 3,
--          docs/modules/asana-task-integration-plan-v1_0.md §4).
--          Workload "overload" is computed from estimated *hours*, not raw task
--          counts. Two pieces:
--            1. est_hours on each template row — the per-task estimate (set once,
--               rides every month). The monthly job stamps it into an Asana
--               number custom field (config asana_effort_field_gid) so the
--               workload read picks it up off the live task.
--            2. asana_team_members — the tracked team list + each person's weekly
--               capacity (hours). Supersedes the env asana_team_member_gids list
--               (kept as a fallback seed); editable in the Workload page.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

alter table asana_client_task_templates
  add column if not exists est_hours numeric;

create table if not exists asana_team_members (
  gid          text primary key,            -- Asana user gid
  name         text,
  weekly_hours numeric,                      -- capacity; null → config default
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

alter table asana_team_members enable row level security;
