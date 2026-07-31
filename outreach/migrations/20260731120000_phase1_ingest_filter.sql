-- Phase 1 — Ingest and filter.
-- Tables are reproduced verbatim from docs/PHASE-1-BRIEF.md §1. Do not "improve" them here;
-- the brief is the owning document for all six.
--
-- No scoring in this phase: prospect_score, scan_snapshot and grid_result are deliberately absent.

create table market (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  radius_miles numeric not null,
  scan_interval_days integer not null default 15,
  created_at timestamptz not null default now()
);

-- Grid geometry is immutable once scanning begins (CLAUDE.md invariants). Changing a centre,
-- radius or spacing invalidates every prior snapshot and resets delta history. Names are editable.
create table submarket (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  name text not null,
  center_lat double precision not null,
  center_lng double precision not null,
  grid_radius_miles numeric not null default 5,
  grid_spacing_miles numeric not null default 1,
  last_scanned_at timestamptz
);

-- Populated in Phase 1 from the market definition; nothing reads it until Phase 2 scanning.
create table keyword (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  term text not null,
  is_primary boolean not null default false,
  unique (market_id, term)
);

-- phone_type is always 'unknown' in Phase 1. Carrier/type comes from Outscraper's
-- phones_enricher_service, which is an enrichment and therefore Phase 5 (ISSUES I-015).
create table prospect (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references market(id) on delete cascade,
  submarket_id uuid references submarket(id),
  place_id text not null unique,
  name text not null,
  category text,
  address text,
  phone text,
  phone_type text check (phone_type in ('mobile','landline','unknown')),
  website text,
  rating numeric,
  review_count integer,
  latest_review_at date,
  lat double precision,
  lng double precision,
  business_status text,
  franchise_status text not null default 'unknown'
    check (franchise_status in ('unknown','flagged','confirmed_franchise','confirmed_independent')),
  raw jsonb not null,
  ingested_at timestamptz not null default now()
);

-- One row per prospect per rule — every rule is evaluated for every prospect, including rules
-- after the first failure. First-match-only logging produces misleading tuning data (brief §3).
create table filter_result (
  prospect_id uuid not null references prospect(id) on delete cascade,
  rule text not null,
  passed boolean not null,
  observed_value text,
  evaluated_at timestamptz not null default now(),
  primary key (prospect_id, rule)
);

create table cost_ledger (
  id bigserial primary key,
  market_id uuid references market(id) on delete cascade,
  cycle_number integer,
  stage text not null,
  provider text not null,
  units integer not null,
  cost_cents integer not null,
  recorded_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- suppression
--
-- OWNED BY docs/crm-layer-spec.md (Phase 1b), which runs in PARALLEL with Phase 1, not after.
-- Created here only so the Phase 1 filter's suppression check is a real left join rather than a
-- to_regclass() guard bolted on later.
--
-- COORDINATION NOTE FOR THE PHASE 1b SESSION: whichever migration runs second must use
-- IF NOT EXISTS. Be aware that this is not a merge — IF NOT EXISTS silently keeps whichever
-- shape was created FIRST and no-ops the other. If the CRM spec's shape differs from this one,
-- reconcile it explicitly with ALTER TABLE; do not assume the second migration corrected it.
-- services/suppression.py reads this table defensively and degrades to "no suppressions" if the
-- columns are not what it expects, which is safe in Phase 1 because nothing is contacted.
-- ---------------------------------------------------------------------------
create table if not exists suppression (
  id uuid primary key default gen_random_uuid(),
  scope text not null,
  value text not null,
  created_at timestamptz not null default now()
);

create unique index if not exists suppression_scope_value_idx on suppression (scope, lower(value));

-- ---------------------------------------------------------------------------
-- Indexes serving the brief §6 definition-of-done queries.
-- ---------------------------------------------------------------------------

create index prospect_market_id_idx on prospect (market_id);
create index prospect_submarket_id_idx on prospect (submarket_id);

-- "Which businesses are flagged as possible franchises and await review."
create index prospect_flagged_idx on prospect (market_id) where franchise_status = 'flagged';

-- "How many failed each rule" / "for any excluded business, which rules it failed."
create index filter_result_rule_passed_idx on filter_result (rule, passed);

create index cost_ledger_market_stage_idx on cost_ledger (market_id, stage);
