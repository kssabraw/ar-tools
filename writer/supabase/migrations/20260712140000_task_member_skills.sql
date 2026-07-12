-- PACE v1.3 Phase 5 (§4.6): per-member role/skill competency map.
--
-- Which task categories (task_categories.key: content / link_building /
-- gbp_authority / strategy) each roster member is competent in. The
-- workload-aware placement engine (services/pm_assign.py) filters candidates to
-- those skilled in a task's category before ranking by remaining capacity.
--
-- A member with NO rows here is treated as a GENERALIST (eligible for any
-- category), so day-one placement works before anyone curates competencies.
-- is_primary breaks ties toward a member's main category; weight is reserved
-- for future proficiency-weighted balancing (unused in v1, default 1).

create table if not exists task_member_skills (
  id           uuid primary key default gen_random_uuid(),
  member_gid   text not null references asana_team_members(gid) on delete cascade,
  category_key text not null references task_categories(key) on delete cascade,
  weight       integer not null default 1,
  is_primary   boolean not null default false,
  created_at   timestamptz not null default now(),
  unique (member_gid, category_key)
);

create index if not exists idx_task_member_skills_gid on task_member_skills(member_gid);

alter table task_member_skills enable row level security;
