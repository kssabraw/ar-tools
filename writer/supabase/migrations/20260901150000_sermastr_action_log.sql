-- Migration: 20260901150000_sermastr_action_log.sql
-- Purpose: SerMaStr Action Log — the audit + learning ledger for what the
--          STRATEGIST proposes and what a human decides on each proposal
--          (approved / dismissed / still pending / senior-required), plus whether
--          the approved tactic actually WORKED (reusing the intervention-outcome
--          loop's verdict — never rebuilding it).
--
--          The strategist PROPOSES and a human approves / dismisses / escalates,
--          so the human decision is the core training signal. One row per PROPOSAL,
--          keyed by the SAME source_ref the interventions loop uses
--          (strategy_proposal:{review_id}:{idx}), so outcome enrichment is a
--          trivial join. Born 'pending' when a review completes, updated in place
--          with the human decision, and stamped with the 6-week worked/partial/
--          no_effect verdict by a daily sweep.
--
--          Two jobs, one stream:
--            1. Debuggability — "what did SerMaStr propose, who decided, and did
--               it work?" (proposal content snapshot, actor, decision, outcome).
--            2. Learning — a training-grade corpus SerMaStr reads back (approve/
--               dismiss rates + worked/no_effect rates per proposal kind + per
--               client) to steer what it proposes.
--
--          Written best-effort at SerMaStr's own seams (review completion + the
--          proposal approve/dismiss endpoint), never at the shared
--          strategy_reviews / interventions layer. strategy_reviews stays the
--          source of truth for proposal CONTENT; this is the queryable,
--          agent-attributed STREAM on top. Gated on settings.sermastr_audit_enabled
--          (default True). Retention: keep everything forever (no pruning).
--
-- RLS on, service-role only (the backend uses the service role key). Reads go
-- through the admin-gated /strategist/action-log API.

create table if not exists public.sermastr_action_log (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz not null default now(),

    -- WHICH PROPOSAL. review_id + idx identify the proposal inside the
    -- strategy_reviews.proposals list; source_ref is the shared idempotency key
    -- (= 'strategy_proposal:{review_id}:{idx}', the SAME key interventions.py
    -- uses) so the outcome sweep joins the two by one column.
    review_id       uuid,
    proposal_idx    integer,
    source_ref      text not null unique,

    -- WHO/WHAT it touched. client_id keeps the row after a client is deleted
    -- (set null) — the audit/training value outlives the client; client_name is
    -- the snapshot for display.
    client_id       uuid references public.clients(id) on delete set null,
    client_name     text,

    -- WHERE IT CAME FROM: the review's trigger.
    trigger         text,   -- 'scheduled' | 'on_demand' | 'escalation' | 'monthly_plan_review'

    -- THE LEARNING KEY: a deterministic proposal kind (target.tactic_type, else
    -- the leading SOP-citation doc token, else 'general').
    proposal_kind   text not null default 'general',

    -- THE PROPOSAL (what + the why).
    title           text,
    action          text,
    sop_citation    text,
    rationale       text,
    -- THE §3 GATE: none | approval | senior (senior = Kyle/Ryan territory).
    requires        text
                      check (requires in ('none', 'approval', 'senior')),
    est_cost_usd    numeric,
    -- The intervention target ({tactic_type, keyword, page_url}) when the
    -- proposal is measurable; null otherwise.
    target          jsonb,

    -- THE HUMAN DECISION. null = still pending (never decided — itself a signal).
    decision        text
                      check (decision in ('approved', 'dismissed')),
    decided_by      uuid,
    decided_at      timestamptz,
    actor_role      text,
    actor_source    text default 'web',   -- 'web' | 'slack' | 'system'

    -- THE OUTCOME (reused from the interventions loop): did the approved,
    -- goal-linked tactic move its metric at the 6-week mark?
    outcome_verdict text
                      check (outcome_verdict in ('worked', 'partial', 'no_effect')),
    outcome_at      timestamptz,
    intervention_id uuid,

    -- Extensibility (review model, token usage ref, etc.).
    context         jsonb
);

-- Query API + self-read reads.
create index if not exists idx_sermastr_action_log_client
  on public.sermastr_action_log (client_id, created_at desc);
create index if not exists idx_sermastr_action_log_kind
  on public.sermastr_action_log (proposal_kind, created_at desc);
create index if not exists idx_sermastr_action_log_decision
  on public.sermastr_action_log (decision, created_at desc);
create index if not exists idx_sermastr_action_log_recent
  on public.sermastr_action_log (created_at desc);

-- The daily outcome sweep scans approved rows still lacking a verdict; a partial
-- index keeps it cheap as the table grows unbounded.
create index if not exists idx_sermastr_action_log_pending_outcome
  on public.sermastr_action_log (created_at desc)
  where decision = 'approved' and outcome_verdict is null;

alter table public.sermastr_action_log enable row level security;

comment on table public.sermastr_action_log is
  'SerMaStr action log: one row per strategist proposal, carrying the proposal (what + why), the human decision (approved/dismissed/pending), the §3 requires-gate, and the reused intervention outcome verdict. Debuggability + a self-read learning corpus. Gated on settings.sermastr_audit_enabled; keep forever.';
comment on column public.sermastr_action_log.source_ref is
  'strategy_proposal:{review_id}:{idx} — the shared key interventions.py uses, so outcome enrichment is a one-column join.';
comment on column public.sermastr_action_log.decision is
  'The human decision on the proposal; null = still pending (itself a training signal).';
comment on column public.sermastr_action_log.outcome_verdict is
  'worked|partial|no_effect from the interventions loop (6-week mark), stamped by the daily outcome sweep for approved goal-linked proposals; null = not yet graded / not measurable.';
