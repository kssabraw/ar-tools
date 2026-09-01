-- Migration: 20260901130000_pace_action_log.sql
-- Purpose: PACE Action Log — the audit + learning ledger for everything PACE
--          does that AFFECTS A CLIENT CAMPAIGN, plus every human decision on
--          those actions (approve / approve-with-modifications / deny / defer /
--          cancel). Deliberately NOT every action — pure reads (delivery report,
--          client pulse, personal brief, drill, history) are excluded.
--
--          Two jobs, one stream:
--            1. Debuggability — "if something went wrong, why?" (before/after
--               snapshot, resolved args, actor, reason, outcome, error).
--            2. Learning — a training-grade corpus PACE reads back (approve/deny/
--               modify patterns per action + per actor) to explain and improve
--               its own behaviour.
--
--          Written best-effort at PACE's own execution/decision seams (never at
--          the shared task_service layer), so every row is PACE-attributed and
--          carries the "why". Gated on settings.pace_audit_enabled (default True).
--
-- RLS on, service-role only (the backend uses the service role key). Reads go
-- through the admin-gated /pace/action-log API.

create table if not exists public.pace_action_log (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz not null default now(),

    -- WHAT: a PACE_ACTIONS key (reassign_task, set_task_status, …) or the
    -- 'intervention_disposition' pseudo-action (the human decision on an
    -- intervention as a whole).
    action          text not null,
    -- WHERE IT CAME FROM: which path staged/executed it.
    origin          text not null default 'conversational'
                      check (origin in ('conversational', 'chase_plan', 'batch',
                                        'intervention', 'scheduled')),
    -- THE HUMAN DECISION (null for a pure system/auto record with no human gate).
    decision        text
                      check (decision in ('approved', 'approved_with_modifications',
                                          'denied', 'deferred', 'cancelled', 'auto')),
    -- WHAT HAPPENED to the action itself.
    outcome         text not null
                      check (outcome in ('executed', 'failed', 'skipped',
                                         'denied', 'deferred', 'cancelled')),

    -- WHO/WHAT it touched. client_id keeps the row after a client is deleted
    -- (set null) — the audit/training value outlives the client; client_name is
    -- the snapshot for display.
    client_id       uuid references public.clients(id) on delete set null,
    client_name     text,
    target_type     text,                                 -- 'task' | 'client' | 'intervention' | 'month'
    target_id       text,
    target_name     text,

    -- WHO decided/confirmed + where, and who originally asked (conversational).
    actor_profile_id     uuid,
    actor_role           text,
    actor_source         text default 'web',              -- 'slack' | 'web' | 'system'
    requester_profile_id uuid,

    -- THE WHY: the confirm line / proposal reason / intervention title.
    reason          text,
    -- THE INTENDED CHANGE: resolved action args.
    args            jsonb not null default '{}'::jsonb,
    -- STATE AROUND THE CHANGE: key task fields before/after (assignee_name,
    -- status_key, due_date, category, est_hours, name, completed).
    before          jsonb,
    after           jsonb,
    -- HUMAN MODIFICATIONS: approve-with-conditions text + parsed directive, or a
    -- Chase-Plan partial selection ({approved:[…], dropped:[…]}).
    modifications   jsonb,

    -- OUTCOME DETAIL.
    result          text,                                 -- the run's success string
    error           text,                                 -- failure detail (truncated)

    -- LINKS / extensibility.
    intervention_id  uuid,
    chase_plan_date  date,
    context          jsonb                                 -- batch id, notification/job id, etc.
);

-- Query API + self-read reads.
create index if not exists idx_pace_action_log_client
  on public.pace_action_log (client_id, created_at desc);
create index if not exists idx_pace_action_log_actor
  on public.pace_action_log (actor_profile_id, created_at desc);
create index if not exists idx_pace_action_log_action
  on public.pace_action_log (action, created_at desc);
create index if not exists idx_pace_action_log_decision
  on public.pace_action_log (decision, created_at desc);
create index if not exists idx_pace_action_log_recent
  on public.pace_action_log (created_at desc);

alter table public.pace_action_log enable row level security;

comment on table public.pace_action_log is
  'PACE action log: one row per client-campaign-affecting PACE action or human disposition (approve/modify/deny/defer/cancel), with before/after + the why. Debuggability + a self-read learning corpus. Gated on settings.pace_audit_enabled.';
