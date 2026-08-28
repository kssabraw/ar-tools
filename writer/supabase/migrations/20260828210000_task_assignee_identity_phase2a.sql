-- Migration: 20260828210000_task_assignee_identity_phase2a.sql
-- Purpose: Native Task Manager — profiles↔gid unification, PHASE 2a
--          (identity finalization; enables LOGIN-LESS VAs).
--
--          ‼ NON-ADDITIVE — but SAFE to apply ahead of the code deploy ‼
--          It changes the roster primary key and makes gid nullable. The one
--          hazard would be the *old* roster editor still on production (a blanket
--          delete-then-reinsert) orphaning the backfilled tasks.assignee_id — so
--          this migration also hardens that FK to ON DELETE RESTRICT (see the
--          bottom), which turns that old path into a loud 500 instead of silent
--          data loss. With that backstop it is safe to apply BEFORE the Phase 2a
--          code deploys; the code is still required for login-less inserts to
--          succeed (gid was NOT NULL until now) and for member removal to work
--          (it unassigns tasks first). See
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

-- Promote id to the primary key by REUSING the existing unique index on id
-- (uq_asana_team_members_id from Phase 1) — the id-referencing FKs (tasks /
-- templates / skills) depend on that index, so it must not be dropped; USING
-- INDEX converts it into the PK in place, keeping those FKs valid.
alter table asana_team_members drop constraint asana_team_members_pkey;   -- was on gid
alter table asana_team_members add primary key using index uq_asana_team_members_id;

-- gid becomes an OPTIONAL external reference (a login-less VA has gid = NULL),
-- unique when present so ON CONFLICT(gid) upserts + any gid lookups still work.
alter table asana_team_members alter column gid drop not null;
create unique index if not exists uq_asana_team_members_gid
  on asana_team_members (gid) where gid is not null;

-- Safety backstop: harden the assignee FK to ON DELETE RESTRICT (was SET NULL).
-- This is what makes applying this migration SAFE even before the Phase 2a code
-- is deployed: the *old* roster editor still on production does a blanket
-- delete-then-reinsert, which under SET NULL would silently orphan all 1041
-- backfilled tasks.assignee_id. Under RESTRICT that delete fails loudly (the
-- members are referenced) — no data loss, just a 500 the admin can't miss. The
-- Phase 2a code removes a member by explicitly unassigning their tasks first
-- (routers/asana.replace_team_members), so intentional removal still works and
-- is now explicit rather than a magic cascade.
alter table tasks drop constraint tasks_assignee_id_fkey;
alter table tasks add constraint tasks_assignee_id_fkey
  foreign key (assignee_id) references asana_team_members(id) on delete restrict;

commit;
