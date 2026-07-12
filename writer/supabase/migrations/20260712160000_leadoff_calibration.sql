-- Migration: 20260712160000_leadoff_calibration.sql
-- Purpose: LeadOff calibration surface Phase 0 (instrumentation only) —
--          docs/modules/leadoff-calibration-plan-v1_0.md, owner-approved
--          2026-07-12. Captures the prediction vector losslessly at the
--          create-client seam and appends read-only outcome checks.
--          NOTHING here changes scoring; Phase 1 tuning is gated on
--          per-metric N>=15 with >=6-month tenure.
-- Both tables are app-owned (public schema) — no market_scanner changes.

create table if not exists leadoff_predictions (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  city_id        bigint not null,
  category_id    text not null,
  category       text not null,
  city_name      text not null,
  state_code     text not null,
  as_of          text,            -- board vintage the assertion was made from
  assumptions    jsonb not null,  -- {capture, lead_tier, lead_value_used}
  predicted      jsonb not null,  -- the full board vector, verbatim
  competitors    jsonb not null,  -- frozen top-5 at selection (rev_win's bar)
  enrichment     jsonb,           -- scout data if present at capture
  model_version  jsonb not null,  -- scoring constants in force (plan §5.2)
  created_by     uuid references profiles(id),
  created_at     timestamptz not null default now()
);

-- one prediction per engagement; immutable by convention (no UPDATE path)
create unique index if not exists uq_leadoff_predictions_client_market
  on leadoff_predictions (client_id, city_id, category_id);

alter table leadoff_predictions enable row level security;

create table if not exists leadoff_outcome_checks (
  id              uuid primary key default gen_random_uuid(),
  prediction_id   uuid not null references leadoff_predictions(id) on delete cascade,
  checked_at      timestamptz not null default now(),
  months_elapsed  numeric(5,1) not null,
  outcome         jsonb not null,  -- plan §3 fields; nulls stay null
  errors          jsonb not null,  -- per-metric signed error where computable
  coverage        jsonb not null default '{}'::jsonb,  -- metric -> why unmeasurable
  actual_leads_mo numeric,         -- manual entry (plan §3.3 path 1)
  leads_source    text check (leads_source in ('manual','gbp_proxy') or leads_source is null)
);

create index if not exists idx_leadoff_outcome_checks_prediction
  on leadoff_outcome_checks (prediction_id, checked_at desc);

alter table leadoff_outcome_checks enable row level security;
