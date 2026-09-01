-- Chronic-emergency escalation (the "still critical" loud re-surface).
--
-- A campaign goal that is critically behind (status behind/overdue) for weeks
-- goes QUIET under the normal machinery: the weekly strategist review keeps
-- producing 0 new proposals (it already proposed everything), so its
-- notification degrades to an indistinguishable "N findings" line, and the
-- scan-over-scan alerts stop firing once nothing is *newly* worse. This table
-- tracks each chronic-behind stint so a daily sweep can re-escalate it loudly
-- on a cadence (services/goal_escalation.py) instead of letting a persistent
-- emergency fade into the background.
--
-- One OPEN row per (client, goal); resolved when the goal is no longer critical.

create table if not exists public.goal_escalations (
    id                uuid primary key default gen_random_uuid(),
    client_id         uuid not null references public.clients(id) on delete cascade,
    goal_id           uuid not null references public.campaign_goals(id) on delete cascade,
    goal_label        text,
    goal_type         text,
    -- When this stint of being behind started. Seeded from the goal's baseline
    -- date when the goal never progressed (so a long-standing chronic goal
    -- escalates immediately rather than waiting out a fabricated future clock),
    -- else the day it slipped.
    behind_since      date not null,
    baseline_value    double precision,
    target_value      double precision,
    current_value     double precision,
    -- Worst measured value seen during this stint (most-behind point).
    worst_value       double precision,
    status            text not null default 'open' check (status in ('open', 'resolved')),
    escalation_count  integer not null default 0,
    last_escalated_at timestamptz,
    resolved_at       timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

-- At most one OPEN escalation per goal (the sweep's idempotency backbone).
create unique index if not exists goal_escalations_one_open_per_goal
    on public.goal_escalations (client_id, goal_id)
    where status = 'open';

create index if not exists goal_escalations_client_status
    on public.goal_escalations (client_id, status);

alter table public.goal_escalations enable row level security;
