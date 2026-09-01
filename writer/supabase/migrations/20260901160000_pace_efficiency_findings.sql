-- Migration: 20260901160000_pace_efficiency_findings.sql
-- Purpose: PACE process-efficiency findings (WS2 — agent-coordination-and-
--          efficiency-plan-v1_0). PACE, the project manager, records where the
--          agency's PROCESSES leak — recurring slips + bottleneck members,
--          rework churn, cadence mistuning, producer noise — as findings
--          ADDRESSED TO DORA. DORA reads this table (WS4) and is the single voice
--          that reports process efficiency to humans; PACE does NOT report these
--          to humans itself. Deterministic detectors, daily inline scan.
--
--          One row per finding, keyed by a stable finding_key so a re-run updates
--          in place; a finding whose key stops appearing is auto-resolved
--          (status -> 'resolved'). Findings are advisory/proposal-worded — nothing
--          is auto-applied. Gated on settings.pace_efficiency_enabled (default
--          False). Retention: keep (resolved rows are the history DORA trends).
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists public.pace_efficiency_findings (
    id             uuid primary key default gen_random_uuid(),
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),

    -- WHICH KIND of process leak.
    category       text not null
                     check (category in ('slip_bottleneck', 'rework', 'cadence',
                                         'producer_noise', 'duplicate_churn')),
    -- Stable identity: a re-run upserts by this; a key that stops appearing
    -- auto-resolves. e.g. 'slip:client:{id}', 'bottleneck:member:{gid}',
    -- 'rework:qa:{client}:{rubric}', 'cadence:month_pace', 'producer_noise:{source}'.
    finding_key    text not null unique,

    -- WHO/WHAT it concerns. client_id nullable (agency-level findings — a
    -- bottleneck member, a cadence problem — have none); on delete set null so
    -- the finding history outlives the client. member_gid is the roster member id
    -- for a bottleneck finding (text; no FK — the roster churns).
    client_id      uuid references public.clients(id) on delete set null,
    member_gid     text,

    -- THE FINDING (proposal-worded — DORA renders/optionally re-narrates it).
    title          text not null,
    detail         text,
    recommendation text,
    evidence       jsonb not null default '{}'::jsonb,
    severity       text not null default 'info'
                     check (severity in ('info', 'warning', 'critical')),

    -- LIFECYCLE. open until no longer detected, then resolved (kept for trends).
    status         text not null default 'open'
                     check (status in ('open', 'resolved')),
    resolved_at    timestamptz,
    last_seen_at   timestamptz not null default now()
);

create index if not exists idx_pace_efficiency_status
  on public.pace_efficiency_findings (status, category);
create index if not exists idx_pace_efficiency_client
  on public.pace_efficiency_findings (client_id, status);
create index if not exists idx_pace_efficiency_open
  on public.pace_efficiency_findings (last_seen_at desc)
  where status = 'open';

alter table public.pace_efficiency_findings enable row level security;

comment on table public.pace_efficiency_findings is
  'PACE process-efficiency findings addressed to DORA (WS2/WS4): slip/bottleneck, rework, cadence, producer-noise. Upserted by finding_key, auto-resolved when no longer detected. Advisory — nothing auto-applied. Gated on settings.pace_efficiency_enabled.';
comment on column public.pace_efficiency_findings.finding_key is
  'Stable identity — a re-run upserts by this; a key that stops appearing auto-resolves.';
