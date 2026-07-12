-- Migration: 20260712120000_domain_intelligence.sql
-- Purpose: Domain Intelligence module (the "SEMrush clone") — Phase 0 foundations.
--   Per-client competitive-intelligence snapshots over the DataForSEO Labs
--   family. See docs/modules/domain-intelligence-module-prd-v1_0.md §5.
--
--   A snapshot row per (client, target domain, run) with child result rows, so
--   every view is a cheap re-read and re-runs are cost-visible. Shape mirrors
--   serp_snapshots / backlink_snapshots.
--
--   * domain_intel_snapshots  — one row per analysis run (rollup metrics)
--   * domain_ranked_keywords  — child: every keyword a domain ranks for
--   * domain_keyword_gaps     — computed gap rows (competitor has, client lacks)
--   * domain_link_gaps        — computed link gap (referring domains client lacks)
--   * domain_intel_usage      — per-day paid-call meter (mirrors backlink_usage)
--   * reserve_domain_intel_calls() — atomic check-and-increment (mirrors
--       reserve_backlink_calls) so concurrent lookups can't overshoot the cap.
--
-- All tables RLS-on with no client-facing policies: access is service-role only,
-- authorization is API-layer client_id filtering (suite single-tenant model).

-- ---------------------------------------------------------------------------
-- Snapshots (one per analysis run)
-- ---------------------------------------------------------------------------
create table if not exists domain_intel_snapshots (
  id                   uuid primary key default gen_random_uuid(),
  client_id            uuid not null references clients (id) on delete cascade,
  target_domain        text not null,
  role                 text not null default 'competitor'
                         check (role in ('competitor', 'client', 'prospect')),
  location_code        integer,
  language_code        text default 'en',
  -- rollups (nullable — a degraded run may fill only some)
  organic_traffic_est  numeric,
  ranked_keyword_count integer,
  dr                   numeric,   -- 0–100 (suite convention: DataForSEO rank / 10)
  rd                   integer,   -- referring domains
  traffic_value_est    numeric,
  status               text not null default 'complete',
  cost_usd             numeric,
  captured_at          timestamptz not null default now()
);

create index if not exists domain_intel_snapshots_client_idx
  on domain_intel_snapshots (client_id, target_domain, captured_at desc);

alter table domain_intel_snapshots enable row level security;

-- ---------------------------------------------------------------------------
-- Ranked keywords (child of a snapshot) — the Ranked Keywords view + gap input
-- ---------------------------------------------------------------------------
create table if not exists domain_ranked_keywords (
  id                  uuid primary key default gen_random_uuid(),
  snapshot_id         uuid not null references domain_intel_snapshots (id) on delete cascade,
  keyword             text not null,
  position            integer,
  url                 text,
  volume              integer,
  cpc_usd             numeric,
  keyword_difficulty  numeric,
  search_intent       text,
  est_value           numeric
);

create index if not exists domain_ranked_keywords_snapshot_idx
  on domain_ranked_keywords (snapshot_id);

alter table domain_ranked_keywords enable row level security;

-- ---------------------------------------------------------------------------
-- Keyword gaps (computed per client + competitor-set run)
-- ---------------------------------------------------------------------------
create table if not exists domain_keyword_gaps (
  id                  uuid primary key default gen_random_uuid(),
  client_id           uuid not null references clients (id) on delete cascade,
  keyword             text not null,
  competitor_domain   text,
  competitor_position integer,
  client_position     integer,   -- null = client absent from the SERP
  volume              integer,
  cpc_usd             numeric,
  keyword_difficulty  numeric,
  gap_type            text check (gap_type in ('missing', 'weak', 'untapped')),
  opportunity_score   numeric,
  captured_at         timestamptz not null default now()
);

create index if not exists domain_keyword_gaps_client_idx
  on domain_keyword_gaps (client_id, captured_at desc);

alter table domain_keyword_gaps enable row level security;

-- ---------------------------------------------------------------------------
-- Link gaps (referring domains linking to a competitor but not the client)
-- ---------------------------------------------------------------------------
create table if not exists domain_link_gaps (
  id                    uuid primary key default gen_random_uuid(),
  client_id             uuid not null references clients (id) on delete cascade,
  referring_domain      text not null,
  linking_to            text[] not null default '{}',  -- competitor domains it links to
  referring_domain_rank numeric,   -- 0–100
  backlink_count        integer,
  captured_at           timestamptz not null default now()
);

create index if not exists domain_link_gaps_client_idx
  on domain_link_gaps (client_id, captured_at desc);

alter table domain_link_gaps enable row level security;

-- ---------------------------------------------------------------------------
-- Daily paid-call budget meter + atomic reservation (mirrors backlink_usage)
-- ---------------------------------------------------------------------------
create table if not exists domain_intel_usage (
  day    date primary key,
  calls  integer not null default 0
);

alter table domain_intel_usage enable row level security;

create or replace function reserve_domain_intel_calls(p_day date, p_n integer, p_cap integer)
returns boolean
language plpgsql
as $$
begin
  insert into domain_intel_usage (day, calls) values (p_day, 0)
    on conflict (day) do nothing;
  update domain_intel_usage
     set calls = calls + p_n
   where day = p_day and calls + p_n <= p_cap;
  return found;
end;
$$;
