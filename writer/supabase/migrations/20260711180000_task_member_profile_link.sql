-- Migration: 20260711180000_task_member_profile_link.sql
-- Purpose: Native task manager — team-identity bridge (PRD §17 Q8, first step
--          of the profiles↔gid unification). Links each tracked team member
--          (asana_team_members, keyed by Asana gid — still the assignee key on
--          tasks) to a suite login user (profiles). Additive + nullable: an
--          unlinked member behaves exactly as before.
--
--          Payoffs this unlocks:
--            * "My Tasks" auto-resolves to the logged-in user's linked member
--              (no more manual "viewing as" for linked people).
--            * A future per-user notification inbox can route task_assigned/
--              task_mention/etc. to the assignee's profile via this link.
--
--          The gid stays the task assignee key — this does NOT rewrite
--          tasks.assignee_gid. It's a bridge, not a migration of the model.

alter table asana_team_members
  add column if not exists profile_id uuid references profiles(id) on delete set null;

-- Reverse lookup: current user → their member gid (My Tasks auto-resolve).
create index if not exists idx_asana_team_members_profile
  on asana_team_members (profile_id) where profile_id is not null;

-- A suite user maps to at most one tracked member (one person, one capacity
-- row). Partial-unique so many members can stay unlinked (null).
create unique index if not exists uq_asana_team_members_profile
  on asana_team_members (profile_id) where profile_id is not null;
