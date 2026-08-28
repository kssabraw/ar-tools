-- Migration: 20260828220000_task_assignee_identity_phase2b.sql
-- Purpose: Native Task Manager — profiles↔gid unification, PHASE 2b
--          (legacy cleanup — drop the now-unused assignee gid columns).
--
--          ‼ STAGED — DO NOT APPLY until the Phase 2b CODE is deployed ‼
--          Unlike Phase 2a there is no safe backstop: dropping a column that
--          the *currently deployed* code still writes breaks that code hard.
--          The Phase 2b code (this branch) stops writing these columns, so this
--          migration is applied ONLY AFTER #845 deploys and is verified in
--          production (grep the deployed code for any remaining reference first).
--          Irreversible — dropped columns cannot be restored. See
--          docs/modules/in-app-task-manager-gid-unification-cutover.md.
--
--          SCOPE: only the two columns with NO legacy-UI coupling —
--            * tasks.assignee_gid          (native tasks; the app now uses
--                                            assignee_id everywhere)
--            * task_member_skills.member_gid (the placement engine uses
--                                            member_id; the table is empty)
--          The other two legacy gid columns — asana_client_task_templates.
--          assignee_gid and asana_client_projects.auto_assignee_gids — are
--          RETAINED here: they are still edited by the legacy AsanaTasks
--          template/eligibility UI. They are dropped in a follow-up once that
--          UI is rewired to member ids.

begin;

-- tasks: drop the legacy assignee gid column + its (partial) index.
drop index if exists idx_tasks_assignee_open;                  -- was on assignee_gid
alter table tasks drop column if exists assignee_gid;

-- task_member_skills: finalize on member_id; drop the legacy member_gid column
-- and its unique/index. (member_id is fully backfilled; the table is empty.)
drop index if exists idx_task_member_skills_gid;
alter table task_member_skills
  drop constraint if exists task_member_skills_member_gid_category_key_key;
alter table task_member_skills drop column if exists member_gid;
alter table task_member_skills alter column member_id set not null;
alter table task_member_skills
  add constraint uq_task_member_skills_member_cat unique (member_id, category_key);

commit;
