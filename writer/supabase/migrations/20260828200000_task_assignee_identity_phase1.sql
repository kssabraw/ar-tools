-- Migration: 20260828200000_task_assignee_identity_phase1.sql
-- Purpose: Native Task Manager — profiles↔gid unification, PHASE 1 (additive).
--          Completes the identity model the PRD (§7, §17 Q8) always intended:
--          a task assignee is a *roster member*, and a roster member is a suite
--          person who MAY (usually) or may NOT (a login-less VA) have a login.
--
--          Decision (owner, 2026-08-28): a first-class roster keyed on its own
--          uuid `id`, with an OPTIONAL `profile_id` link to a suite login — NOT a
--          collapse onto profiles.id (which is `auth.users.id`; a profile IS a
--          login, so it cannot represent a login-less worker). Assignee/skills/
--          auto-assign eligibility key on the roster id; actors/authors stay on
--          profiles.id (already correct — created_by / actor_id / mentions).
--
--          PHASE 1 is deliberately ADDITIVE and backward-compatible: the live
--          PLATFORM service still runs the current gid-based code, so this
--          migration adds the new id-based columns ALONGSIDE the old gid columns
--          and backfills them. Nothing is renamed, no PK changes, nothing is
--          dropped — old and new code coexist during the deploy window, and the
--          code re-key dual-writes both keys through the parallel-run cycle.
--
--          PHASE 2 (cutover migration, later): rename asana_team_members →
--          team_members, make its gid (→ asana_gid) nullable + id the PK (which
--          is what enables adding a login-less VA with no Asana gid), and drop
--          assignee_gid / member_gid / auto_assignee_gids. See the phase-2 file.
--
--          Backfill is exact: measured live, all task/template/auto-assign gids
--          resolve to the 4-member roster (zero orphans). Historical JSONB
--          (task_activity.detail, notifications.payload) is left untouched — it
--          is immutable audit, name-cached, and still resolves via the roster's
--          retained gid.
--
-- RLS on, service-role only (suite convention) — the new columns inherit it.

begin;

-- ---------------------------------------------------------------------------
-- 1. Roster gets its own uuid identity (alongside the gid PK, which stays).
--    FKs below reference this UNIQUE id (Postgres allows an FK to any unique
--    column, not only the PK), so Phase 2 can promote it to PK transparently.
-- ---------------------------------------------------------------------------
alter table asana_team_members
  add column if not exists id uuid not null default gen_random_uuid();

create unique index if not exists uq_asana_team_members_id
  on asana_team_members (id);

-- ---------------------------------------------------------------------------
-- 2. tasks.assignee_id — the new assignee key. Backfill from assignee_gid via
--    the roster. Keep assignee_gid + its index for dual-write / rollback.
-- ---------------------------------------------------------------------------
alter table tasks
  add column if not exists assignee_id uuid references asana_team_members(id) on delete set null;

update tasks t
   set assignee_id = m.id
  from asana_team_members m
 where m.gid = t.assignee_gid
   and t.assignee_gid is not null
   and t.assignee_id is null;

create index if not exists idx_tasks_assignee_id_open
  on tasks (assignee_id) where completed = false and deleted_at is null;

-- ---------------------------------------------------------------------------
-- 3. asana_client_task_templates.assignee_id — the per-client template default
--    assignee monthly generation seeds from. Backfill; keep the gid column.
-- ---------------------------------------------------------------------------
alter table asana_client_task_templates
  add column if not exists assignee_id uuid references asana_team_members(id) on delete set null;

update asana_client_task_templates tpl
   set assignee_id = m.id
  from asana_team_members m
 where m.gid = tpl.assignee_gid
   and tpl.assignee_gid is not null
   and tpl.assignee_id is null;

-- ---------------------------------------------------------------------------
-- 4. task_member_skills.member_id — the placement engine's competency key.
--    Nullable in Phase 1 (old deployed code writes member_gid only); Phase 2
--    makes it NOT NULL and drops member_gid. Empty table today, but backfill
--    for correctness.
-- ---------------------------------------------------------------------------
alter table task_member_skills
  add column if not exists member_id uuid references asana_team_members(id) on delete cascade;

update task_member_skills s
   set member_id = m.id
  from asana_team_members m
 where m.gid = s.member_gid
   and s.member_id is null;

create index if not exists idx_task_member_skills_member
  on task_member_skills (member_id);

-- ---------------------------------------------------------------------------
-- 5. asana_client_projects.auto_assignee_ids — id-based eligibility (jsonb
--    array of roster ids), alongside the gid jsonb array. All rows are []
--    today, but map any populated ones exactly.
-- ---------------------------------------------------------------------------
alter table asana_client_projects
  add column if not exists auto_assignee_ids jsonb not null default '[]'::jsonb;

update asana_client_projects p
   set auto_assignee_ids = coalesce((
         select jsonb_agg(m.id)
           from jsonb_array_elements_text(p.auto_assignee_gids) g
           join asana_team_members m on m.gid = g.value
       ), '[]'::jsonb)
 where p.auto_assignee_gids is not null
   and p.auto_assignee_gids <> '[]'::jsonb;

commit;
