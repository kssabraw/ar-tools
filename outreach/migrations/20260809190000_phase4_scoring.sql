-- Migration: 20260809190000_phase4_scoring.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Phase 4 Stage 1 — the scoring data model. Creates the tables the
--            sabermetric scorecard writes into (`score_run`, `prospect_score`),
--            the soft eligibility flag (`conflict_check`), and the side-by-side
--            ranked read surface (`v_prospect_ranked`) that the §10 acceptance
--            criteria call for. Replaces the coverage-deficit PLACEHOLDER
--            (`v_prospect_placeholder_score`) as the authoritative ranking wherever
--            a score_run exists; the placeholder is subordinated, not dropped
--            (ISSUES I-082 — it was made a view precisely so it survives as the
--            zero-score fallback and is removed in one line when it is no longer
--            read at all).
--
-- AUTHORITY: the three tables are adopted VERBATIM from
-- `docs/PRD-prospect-pipeline.md` (START-HERE §3a names the PRD as their owner),
-- reconciled with `docs/scoring-spec.md` §8. Where the two differ the PRD is the
-- superset the reporting layer already reads (`pass`, `channel`, `primary_pitch`,
-- `evidence_age_days` on `prospect_score`; `cycle_number` on `score_run`), so the
-- PRD shape is the one built.
--
-- WHY NOW: Phase 3 is producing audits and the `outcome`/`touch` substrate is live
-- (migration 20260809170000). Stage 1 (priors) needs no real outcomes — only the
-- elicited coefficients already in the spec — so the ENGINE, its tables, and the
-- golden-fixture harness are buildable now; Stages 2–3 wait on accumulated
-- `outcome` rows. Rank order is a strong PRIOR, not a prediction, until ~100
-- prospects have been contacted (CLAUDE.md → What is unvalidated).

-- ---------------------------------------------------------------------------
-- score_run — one scoring pass over a market's prospects. Immutable history:
-- a re-score inserts a NEW run, never updates an old one (scoring-spec §6 Stage 1
-- "log everything"), so a score cited to a prospect in March regenerates in June.
--
-- `lambda_shrink` and the calibration constants are stamped on the RUN, not the
-- row, because they are uniform across every prospect in the run — λ is a single
-- multiplier that cannot change rank order (CLAUDE.md trap), and α/γ come from the
-- Stage-2 recalibration that fits one pair per run. NULL α/γ = Stage 1 (priors
-- only), which is the flag the display-probability clamp reads (acceptance §5).
-- ---------------------------------------------------------------------------
create table if not exists score_run (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  cycle_number integer not null,
  model_version text not null,
  lambda_shrink numeric not null,
  calibration_alpha numeric,
  calibration_gamma numeric,
  created_at timestamptz not null default now()
);

create index if not exists score_run_market_idx on score_run (market_id, created_at desc);

-- ---------------------------------------------------------------------------
-- prospect_score — one score per (prospect, run, model, pass, channel).
--
-- `channel` is in the PRIMARY KEY, so Postgres makes it NOT NULL. That is the
-- design, not an accident: Model B (close) is channel-independent in its
-- coefficients (scoring-spec §3, "both"), but it is still STAMPED with the channel
-- of the reply it composes into a `value` — value(phone) = p_reply(phone) ×
-- p_close, value(email) = p_reply(email) × p_close — so close(phone) and
-- close(email) are distinct rows with identical points. Pooling phone and email in
-- one ranked list is forbidden (scoring-spec §1); carrying channel on every row is
-- what enforces that at the read surface.
--
-- `raw_points` is numeric (Σ of the prior integer points; value/composition rows
-- store 0). `score` is TargetScore + λ × raw_points. `predicted_prob` is the RAW
-- inverse-logit — the ≤60% display clamp (acceptance §5) is applied at READ time
-- (v_prospect_ranked.display_prob) so the stored probability stays the honest model
-- output. `score_factors` is the replayable audit trail: for a scorecard model,
-- Σ points × λ + TargetScore reproduces `score` exactly (acceptance §1).
-- ---------------------------------------------------------------------------
create table if not exists prospect_score (
  prospect_id uuid not null references prospect(id) on delete cascade,
  score_run_id uuid not null references score_run(id) on delete cascade,
  model text not null check (model in ('reply','close','value')),
  pass smallint not null check (pass in (1,2)),
  channel text not null check (channel in ('phone','email')),
  raw_points numeric not null,
  score numeric not null,
  predicted_prob numeric,
  decile smallint,
  primary_pitch text,
  evidence_age_days integer not null,
  score_factors jsonb not null,
  primary key (prospect_id, score_run_id, model, pass, channel)
);

create index if not exists prospect_score_run_idx on prospect_score (score_run_id, model, channel);

-- ---------------------------------------------------------------------------
-- conflict_check — a SOFT eligibility flag, adopted verbatim from the PRD.
--
-- scoring-spec §8: "Do NOT let it modify the score — conflict is an eligibility
-- question, not a quality one, and blending it into the score would hide the
-- judgment call the policy exists to preserve." So it is a separate table with no
-- reference to score_run and no join into prospect_score's score. `risk_level` is
-- computed from vertical match × service-area overlap; an explicit `decision` is
-- required before a prospect enters a sequence. It is a badge, never a filter.
-- ---------------------------------------------------------------------------
create table if not exists conflict_check (
  prospect_id uuid primary key references prospect(id) on delete cascade,
  existing_client_id text,
  vertical_match boolean not null,
  market_overlap_pct numeric,
  risk_level text not null check (risk_level in ('none','low','high')),
  reviewed_by text,
  decision text
);

-- ---------------------------------------------------------------------------
-- v_prospect_ranked — the §10 acceptance surface: "Rank order under all three
-- models exposed side-by-side in the prospect table."
--
-- Reconciliation (ISSUES I-082 / DECISIONS 2026-08-05): the placeholder migration
-- and the 2026-08-05 decision entry both refer to `v_prospect_ranked` as a view
-- that "already selects prospect_score where pass = 2 and model = 'value'". That
-- was aspirational — the view was never built, and the reporting spec's operator
-- queue is a DIFFERENT view (`v_prospect_queue`, reporting-layer-spec §3.1, still
-- unbuilt because it needs the enrichment/case_study tables). This IS that view,
-- now real. It does NOT hard-code pass = 2: with no email enrichment yet, Stage 1
-- scores the phone track at pass 1, so pinning pass = 2 would show an empty table.
--
-- The view anchors on the `reply` model (always produced) and left-joins `close`
-- and `value` on the SAME (prospect, channel, pass), pivoting the three models into
-- one row. It reads only the LATEST run per market, so it re-resolves to current
-- scores while each score_run stays independently citable.
--
-- `display_prob` applies the acceptance-§5 clamp at the read surface: until the run
-- has a calibration_alpha, probabilities are ordinal-only and capped at 0.60. The
-- 0.60 literal mirrors the engine's `display_prob_clamp_pct` default; both cite the
-- same PRD rule, and a test pins the engine value.
-- ---------------------------------------------------------------------------
create or replace view v_prospect_ranked
with (security_invoker = true) as
with latest_run as (
  select distinct on (market_id)
         id, market_id, cycle_number, model_version,
         lambda_shrink, calibration_alpha, calibration_gamma, created_at
    from score_run
   order by market_id, created_at desc, id desc
)
select
  p.id                          as prospect_id,
  p.market_id,
  p.submarket_id,
  p.name,
  p.phone,
  reply.channel,
  reply.pass,
  reply.score                   as reply_score,
  reply.predicted_prob          as reply_prob,
  case when lr.calibration_alpha is null
       then least(reply.predicted_prob, 0.60)
       else reply.predicted_prob end                   as reply_display_prob,
  reply.decile                  as reply_decile,
  close.score                   as close_score,
  close.predicted_prob          as close_prob,
  close.decile                  as close_decile,
  val.score                     as value_score,
  val.predicted_prob            as value_prob,
  val.decile                    as value_decile,
  coalesce(val.primary_pitch, reply.primary_pitch)     as primary_pitch,
  reply.evidence_age_days,
  lr.id                         as score_run_id,
  lr.model_version,
  lr.lambda_shrink,
  lr.calibration_alpha,
  lr.created_at                 as scored_at
from latest_run lr
join prospect p
  on p.market_id = lr.market_id
join prospect_score reply
  on reply.score_run_id = lr.id
 and reply.prospect_id = p.id
 and reply.model = 'reply'
left join prospect_score close
  on close.score_run_id = lr.id
 and close.prospect_id = p.id
 and close.model = 'close'
 and close.channel = reply.channel
 and close.pass = reply.pass
left join prospect_score val
  on val.score_run_id = lr.id
 and val.prospect_id = p.id
 and val.model = 'value'
 and val.channel = reply.channel
 and val.pass = reply.pass
-- Phone and email are never pooled: order WITHIN a channel. `value` is the
-- operative ranking under flat pricing (scoring-spec §4, p_reply × p_close);
-- reply breaks ties and orders any channel with no value row.
order by reply.channel, val.score desc nulls last, reply.score desc;

comment on view v_prospect_ranked is
  'Phase 4 side-by-side ranked scores (scoring-spec §10): the latest score_run per '
  'market, reply/close/value pivoted per prospect x channel x pass, ordered by value '
  'score within a channel. Supersedes v_prospect_placeholder_score as the ranking '
  'wherever a score_run exists. display_prob clamps to 0.60 until calibration_alpha '
  'is non-null (acceptance §5).';

comment on view v_prospect_placeholder_score is
  'SUBORDINATED by v_prospect_ranked (Phase 4, migration 20260809190000). Retained as '
  'the zero-model coverage-deficit fallback for submarkets with no score_run yet, and '
  'removed in one line once nothing reads it (ISSUES I-082). Was the Phase-2 placeholder '
  'ranking; a fitted score now supersedes it.';

-- ---------------------------------------------------------------------------
-- Access model → suite standard (HANDOFF §2 / CLAUDE.md invariants). RLS ENABLED,
-- ZERO policies, no grants to anon/authenticated: reachable only through the
-- service role platform-api holds. REVOKE FIRST — Supabase grants ALL on new
-- public tables to anon/authenticated by default, so a bare grant removes nothing.
-- ---------------------------------------------------------------------------
alter table score_run      enable row level security;
alter table prospect_score enable row level security;
alter table conflict_check enable row level security;
revoke all on score_run      from anon, authenticated;
revoke all on prospect_score from anon, authenticated;
revoke all on conflict_check from anon, authenticated;

-- Views inherit invoker rights (security_invoker) and are reachable only through
-- the service role; revoke to match posture.
revoke all on v_prospect_ranked from anon, authenticated;
