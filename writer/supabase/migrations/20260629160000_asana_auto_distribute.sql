-- Migration: 20260629160000_asana_auto_distribute.sql
-- Purpose: Asana monthly automation — automatic task distribution (capacity-aware).
--          A template row can be marked `auto_assign` (no fixed assignee); the
--          monthly job then distributes those tasks across the client's eligible
--          team members, giving each task to whoever has the most remaining
--          capacity (weekly_hours − current open hours, weighted by est_hours).
--          `auto_assignee_gids` is the per-client eligibility list (which tracked
--          team members may receive that client's auto-distributed tasks).
--
-- Both additive; pinned rows (a specific assignee) are unaffected.

alter table asana_client_task_templates
  add column if not exists auto_assign boolean not null default false;

alter table asana_client_projects
  add column if not exists auto_assignee_gids jsonb not null default '[]'::jsonb;
