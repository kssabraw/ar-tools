-- Migration: 20260829150000_pace_interventions.sql
-- Purpose: PACE Proactive Interventions — the managerial layer over the native
--          task board (docs/modules/pace-proactive-interventions-plan-v1_0.md).
--          PACE scans for systemic delivery problems (severe member overload,
--          ambiguous duplicate task names blocking automation, untriaged /
--          overdue clusters, forecast slip clusters) and opens ONE durable
--          intervention per problem — a problem + a concrete fix plan the PM
--          dispositions four ways (approve / deny / defer / approve-with-
--          conditions). Approve executes the plan through the tested PACE_ACTIONS
--          stage→run path; every fix is reversible.
--
--          Ships dark behind settings.pace_interventions_enabled (default False),
--          on top of the existing pace_enabled + pace_initiative_enabled flags.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists public.pace_interventions (
    id              uuid primary key default gen_random_uuid(),
    -- Which detector opened it.
    kind            text not null check (kind in (
                      'member_overload', 'duplicate_names', 'untriaged_backlog',
                      'overdue_cluster', 'slip_forecast')),
    -- The client the problem is scoped to; null for agency-wide problems (e.g.
    -- a member overloaded across several clients).
    scope_client_id uuid references public.clients(id) on delete cascade,
    -- Stable identity of the open problem (e.g. 'member_overload:<member_id>',
    -- 'duplicate_names:<client_id>') — the idempotency key: one OPEN row per
    -- signature (partial unique index below).
    signature       text not null,
    severity        text not null default 'warning'
                      check (severity in ('info', 'warning', 'critical')),
    title           text not null,
    problem         text not null default '',           -- what's wrong + numbers
    -- {actions:[{action, client_id, client_name, args, reason, perm}], summary,
    --  overflow} — the concrete fix; each action is a PACE_ACTIONS entry.
    plan            jsonb not null default '{}'::jsonb,
    plan_fingerprint text,                                -- hash of the action list (drift detection)
    evidence        jsonb not null default '{}'::jsonb,   -- raw metrics for the panel
    status          text not null default 'proposed'
                      check (status in ('proposed', 'deferred', 'executing',
                                        'executed', 'failed', 'denied',
                                        'resolved', 'superseded')),
    disposition     text,                                 -- last human disposition verb
    conditions      text,                                 -- free-text constraint (approve-with-conditions)
    deferred_until  date,                                 -- snooze target (status='deferred')
    decided_by      uuid,                                 -- profile_id of the PM who dispositioned
    decided_at      timestamptz,
    -- {ran:[...], skipped:[...], failed:[...], summary} — execution outcome.
    result          jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- One OPEN intervention per problem signature (the dedup). 'executing' counts as
-- open so a scan mid-execution never opens a duplicate.
create unique index if not exists uq_pace_interventions_open_signature
  on public.pace_interventions (signature)
  where status in ('proposed', 'deferred', 'executing');

-- Panel + scan reads.
create index if not exists idx_pace_interventions_status
  on public.pace_interventions (status, severity, created_at desc);
create index if not exists idx_pace_interventions_signature_recent
  on public.pace_interventions (signature, created_at desc);
create index if not exists idx_pace_interventions_client
  on public.pace_interventions (scope_client_id, created_at desc);

alter table public.pace_interventions enable row level security;

comment on table public.pace_interventions is
  'PACE proactive interventions: one durable proposal per systemic delivery problem, dispositioned approve/deny/defer/approve-with-conditions. Dark behind settings.pace_interventions_enabled.';
