-- Strategy actions saved out of a SerMaStr conversation into the Action Plan.
--
-- The Action Plan is regenerated from signals on every build (`reopt_planner.
-- build_plan` rebuilds `reopt_plans.items` wholesale), so an action authored in
-- a conversation cannot live in that table — the next rebuild would erase it.
-- These rows are the durable half: `build_plan` reads them and merges them into
-- the ranked list each time, so a saved step survives every rebuild until
-- somebody closes it.
--
-- Recommend-only, like every other Action Plan row: saving a step schedules
-- nothing and executes nothing. It puts the work where the team already looks.
create table if not exists public.assistant_plan_actions (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid        not null references public.clients(id) on delete cascade,
  -- The step itself, and why — mirrors an action's recommendation/diagnosis.
  title       text        not null,
  detail      text,
  -- Optional deep link into the tool that does the work; defaults to the plan.
  cta_label   text,
  cta_path    text,
  -- Grouping label shown in the plan's keyword column (e.g. the target keyword).
  keyword     text,
  created_by  uuid        references public.profiles(id) on delete set null,
  status      text        not null default 'active'
                          check (status in ('active', 'done', 'dismissed')),
  created_at  timestamptz not null default now(),
  closed_at   timestamptz
);

comment on table public.assistant_plan_actions is
  'Action Plan steps saved from a SerMaStr strategy conversation. Merged into reopt_plans on every build so they survive rebuilds. Recommend-only.';

create index if not exists assistant_plan_actions_client_status_idx
  on public.assistant_plan_actions (client_id, status, created_at desc);

alter table public.assistant_plan_actions enable row level security;

drop policy if exists "service manages assistant_plan_actions" on public.assistant_plan_actions;
create policy "service manages assistant_plan_actions"
  on public.assistant_plan_actions for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
