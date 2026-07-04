-- Migration: 20260704140000_recipe_engine.sql
-- Purpose: Link Building & Campaign Recipe Engine (docs/sops/
--          Link_Building_Recipe_Engine.md). Turns a client's retainer +
--          diagnosis into a costed, assigned monthly task plan (SOP §1–§5).
--
--          * clients gains the budget inputs the allocation formula needs:
--            retainer_monthly (the §1 input), is_sab (the baseline stack's
--            GBP-Blast exclusion), client_type (the §3 funding order:
--            local → RD first; enterprise → Entity first).
--          * monthly_task_plans stores each generated plan (the §5 output
--            contract in `plan`, with headline columns for listing).
--
-- RLS on, service-role only (the backend uses the service role key).

alter table clients add column if not exists retainer_monthly numeric;
alter table clients add column if not exists is_sab boolean not null default false;
alter table clients add column if not exists client_type text not null default 'local'
  check (client_type in ('local', 'enterprise'));

create table if not exists monthly_task_plans (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  month       date not null,                -- first day of the plan month
  margin_used numeric not null,             -- 0.34 default / 0.50 stagnating-or-drop
  deployable  numeric not null,
  spent       numeric not null,
  remaining   numeric not null,
  flags       text[] not null default '{}',
  plan        jsonb not null,               -- full §5 output contract (tasks[], diagnosis, …)
  created_by  uuid references profiles(id),
  created_at  timestamptz not null default now()
);

create index if not exists idx_monthly_task_plans_client_month
  on monthly_task_plans (client_id, month desc, created_at desc);

alter table monthly_task_plans enable row level security;
