-- Migration: 20260901170000_agent_messages.sql
-- Purpose: Agent-to-agent coordination bus (WS3 — agent-coordination-and-
--          efficiency-plan-v1_0). A DB-backed message/inbox log that makes the
--          agents' implicit handoffs EXPLICIT and MEASURABLE, so DORA can oversee
--          how work flows between SerMaStr / PACE / QA / autonomy and flag
--          coordination inefficiencies (stalled handoffs, capacity blockers,
--          latency). No new infra — polled on each agent's scheduled run, like
--          every other shared-scheduler consumer.
--
--          A message: who → whom (or broadcast), a kind (handoff/request/notice/
--          blocker/ack), the entity it references, a correlation_id threading a
--          handoff conversation, and a lifecycle (open → acted/dismissed). Gated
--          on settings.agent_bus_enabled (default False). Additive + best-effort
--          — posting never breaks a hot path.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists public.agent_messages (
    id             uuid primary key default gen_random_uuid(),
    created_at     timestamptz not null default now(),

    from_agent     text not null
                     check (from_agent in ('sermastr', 'pace', 'qa', 'autonomy', 'dora')),
    -- 'broadcast' = addressed to every agent (DORA reads all regardless).
    to_agent       text not null
                     check (to_agent in ('sermastr', 'pace', 'qa', 'autonomy', 'dora', 'broadcast')),

    client_id      uuid references public.clients(id) on delete set null,
    kind           text not null
                     check (kind in ('handoff', 'request', 'notice', 'blocker', 'ack')),
    subject        text,
    body           text,
    -- The entity this concerns (a task id, a proposal source_ref, a finding_key).
    ref            text,
    -- Threads a handoff conversation (e.g. the proposal source_ref), so a reply/
    -- ack joins its originating message.
    correlation_id text,
    -- Optional idempotency key: post() skips when an OPEN message already carries
    -- it (so a daily re-post of the same finding notice is a no-op).
    dedupe_key     text,

    status         text not null default 'open'
                     check (status in ('open', 'read', 'acted', 'dismissed')),
    acted_at       timestamptz,
    acted_by       text,   -- the agent that acted/acked

    payload        jsonb not null default '{}'::jsonb
);

create index if not exists idx_agent_messages_inbox
  on public.agent_messages (to_agent, status, created_at desc);
create index if not exists idx_agent_messages_correlation
  on public.agent_messages (correlation_id);
create index if not exists idx_agent_messages_recent
  on public.agent_messages (created_at desc);
create index if not exists idx_agent_messages_open
  on public.agent_messages (created_at desc)
  where status = 'open';

alter table public.agent_messages enable row level security;

comment on table public.agent_messages is
  'Agent-to-agent coordination bus (WS3): explicit handoffs/requests/notices/blockers/acks between SerMaStr/PACE/QA/autonomy, so DORA can measure coordination health. Gated on settings.agent_bus_enabled; additive + best-effort.';
comment on column public.agent_messages.correlation_id is
  'Threads a handoff conversation (e.g. a proposal source_ref) so an ack joins its originating message.';
comment on column public.agent_messages.dedupe_key is
  'Optional idempotency key — post() skips when an OPEN message already carries it.';
