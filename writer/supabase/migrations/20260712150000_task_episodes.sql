-- PACE v1.4 Phase 9 (§4.9): follow-through episodes — the chase loop's clock.
--
-- One OPEN episode per (task, kind ∈ stale|overdue|unassigned|unacted). Opened
-- when pm_signals first detects the condition; movement (any task_activity
-- beyond created/placement_deferred) resets the escalation clock; a single
-- public escalation fires after pace_chase_escalate_business_days without
-- movement; resolved when the signal clears. last_proposed_at/nudge_count pace
-- the daily Chase Plan re-proposals (pace_chase_renudge_days).

create table if not exists task_episodes (
  id               uuid primary key default gen_random_uuid(),
  task_id          uuid not null references tasks(id) on delete cascade,
  kind             text not null,                      -- stale | overdue | unassigned | unacted
  status           text not null default 'open',      -- open | resolved
  opened_at        timestamptz not null default now(),
  last_movement_at timestamptz,
  last_proposed_at timestamptz,
  nudge_count      integer not null default 0,
  escalated_at     timestamptz,
  resolved_at      timestamptz
);

create unique index if not exists uq_task_episodes_open
  on task_episodes(task_id, kind) where status = 'open';
create index if not exists idx_task_episodes_status on task_episodes(status);

alter table task_episodes enable row level security;
