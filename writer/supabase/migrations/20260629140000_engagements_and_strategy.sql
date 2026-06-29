-- ============================================================
-- Managed engagement spine + strategy plan data model
-- ============================================================
-- The foundation for "SerMaStr" (the managed-engagement + Continuous Strategist
-- layer — see docs/managed-engagement-and-strategy-engine-design-v1_0.md §3.1).
-- This migration creates the engagement state machine and the unified strategy
-- plan/action tables the Strategy Engine writes into (recommend-only for now).
-- Additive; nothing else depends on these yet.
-- ============================================================

-- ── engagements: one active managed engagement per client ────────────────────
create table if not exists engagements (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  status          text not null default 'onboarding'
                    check (status in (
                      'onboarding', 'intake', 'auditing', 'strategizing',
                      'plan_review', 'provisioning', 'executing', 'steady_state',
                      'paused', 'closed'
                    )),
  autonomy_level  text not null default 'assisted'
                    check (autonomy_level in ('recommend', 'assisted', 'autonomous')),
  config          jsonb not null default '{}'::jsonb,   -- budgets, checkpoints, publish_mode, capacity
  current_plan_id uuid,                                 -- FK added after strategy_plans exists
  created_by      uuid references profiles(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- At most one non-closed engagement per client.
create unique index if not exists uniq_active_engagement_per_client
  on engagements (client_id) where status <> 'closed';

create index if not exists idx_engagements_client
  on engagements (client_id, created_at desc);

alter table engagements enable row level security;


-- ── strategy_plans: a versioned, approvable plan per engagement ───────────────
create table if not exists strategy_plans (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references engagements(id) on delete cascade,
  version       integer not null default 1,
  status        text not null default 'proposed'
                  check (status in ('draft', 'proposed', 'approved', 'superseded')),
  summary       jsonb,                                  -- scores, headline findings
  approved_by   uuid references profiles(id),
  approved_at   timestamptz,
  created_at    timestamptz not null default now()
);

create index if not exists idx_strategy_plans_engagement
  on strategy_plans (engagement_id, created_at desc);

alter table strategy_plans enable row level security;

-- Now the engagement can point at its current plan.
alter table engagements
  add constraint engagements_current_plan_fk
  foreign key (current_plan_id) references strategy_plans(id) on delete set null;


-- ── strategy_actions: the unit the executor OR Asana consumes ─────────────────
create table if not exists strategy_actions (
  id             uuid primary key default gen_random_uuid(),
  plan_id        uuid not null references strategy_plans(id) on delete cascade,
  module         text not null default 'organic'
                   check (module in ('organic', 'maps', 'ai_visibility', 'cross')),
  category       text not null
                   check (category in (
                     'silo', 'page', 'onpage', 'internal_link', 'citation',
                     'backlink', 'llm_tactic', 'technical_fix', 'tracking_setup',
                     'schedule', 'gbp', 'reviews'
                   )),
  kind           text,                                  -- e.g. rank_drop, maps_coverage_gap, llm_content_gap
  title          text not null,
  rationale      text,
  target         jsonb,                                 -- keyword/url/location/etc
  priority       integer not null default 0,
  effort         text check (effort in ('low', 'medium', 'high')),
  est_value      numeric,
  execution_mode text not null default 'assigned'
                   check (execution_mode in ('auto', 'assigned')),
  assignee_role  text check (assignee_role in (
                     'writer', 'seo_tech', 'link_builder', 'va', 'account_manager'
                   )),
  source         text not null default 'initial_plan'
                   check (source in ('initial_plan', 'strategist_signal')),
  status         text not null default 'proposed'
                   check (status in (
                     'proposed', 'approved', 'queued', 'in_progress',
                     'assigned', 'done', 'blocked', 'skipped'
                   )),
  job_id         uuid,                                  -- async_jobs id when auto-executed
  asana_task_id  text,                                  -- Asana gid when assigned
  result         jsonb,
  deep_link      text,
  created_at     timestamptz not null default now()
);

create index if not exists idx_strategy_actions_plan
  on strategy_actions (plan_id, priority desc);

alter table strategy_actions enable row level security;
