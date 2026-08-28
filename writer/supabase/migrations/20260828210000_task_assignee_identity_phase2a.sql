-- Migration: 20260828210000_task_assignee_identity_phase2a.sql
-- Purpose: Native Task Manager — profiles↔gid unification, PHASE 2a
--          (identity finalization; enables LOGIN-LESS VAs).
--
--          ‼ NON-ADDITIVE — DO NOT APPLY UNTIL THE PHASE 2a CODE IS DEPLOYED ‼
--          Apply this in lockstep with the Phase 2a code deploy, and only AFTER
--          Phase 1 (20260828200000) is live in production. It changes the roster
--          primary key and drops a foreign key that the *currently deployed*
--          pre-Phase-1 code relies on — applying it while prod still runs the old
--          gid-based roster editor (delete-then-reinsert) would orphan the
--          backfilled tasks.assignee_id (ON DELETE SET NULL). It is intentionally
--          NOT applied by the branch that introduces it; see
--          docs/modules/in-app-task-manager-gid-unification-cutover.md.
--
--          After this migration a roster member's identity is its uuid `id`, and
--          `gid` (the Asana user gid) is an OPTIONAL external reference — so a
--          member can exist with no gid: a VA who never logs into AR Tools.
--
--          Legacy gid columns (tasks.assignee_gid, asana_client_task_templates.
--          assignee_gid, task_member_skills.member_gid, asana_client_projects.
--          auto_assignee_gids) are dropped in Phase 2b, not here.

begin;

-- The skills FK references asana_team_members(gid)'s FULL unique constraint (its
-- PK). An FK cannot be backed by a partial unique index, so drop the FK before
-- gid stops being the PK. Skills are already keyed on member_id (Phase 1); the
-- member_gid column itself is dropped in Phase 2b.
alter table task_member_skills
  drop constraint if exists task_member_skills_member_gid_fkey;

-- Promote id to the primary key.
alter table asana_team_members drop constraint asana_team_members_pkey;   -- was on gid
drop index if exists uq_asana_team_members_id;                            -- redundant once id is the PK
alter table asana_team_members add primary key (id);

-- gid becomes an OPTIONAL external reference (a login-less VA has gid = NULL),
-- unique when present so ON CONFLICT(gid) upserts + any gid lookups still work.
alter table asana_team_members alter column gid drop not null;
create unique index if not exists uq_asana_team_members_gid
  on asana_team_members (gid) where gid is not null;

commit;
