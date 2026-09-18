-- LeadOff valuation v1 (step 2): the national-median-CPC baseline for the
-- per-market CPC local modifier on CPL (docs/modules/leadoff-valuation-plan-v1_0.md §3).
--
-- App-owned (public.*), so a market_scanner reload cannot wipe it (the
-- reload-wipe rule). Holds the median Google Ads CPC per category, computed from
-- market_scanner.market_opportunity_master.category_cpc by
-- scripts/build_cpc_baseline.py; the modifier reads it (services/leadoff_cpc.py)
-- and degrades to x1.0 for any category not present. Refreshable + idempotent.

create table if not exists public.leadoff_cpc_baseline (
    category_name text primary key,
    median_cpc numeric not null,
    n integer not null default 0,
    computed_at timestamptz not null default now()
);

comment on table public.leadoff_cpc_baseline is
    'LeadOff national median Google Ads CPC per category (from market_scanner.market_opportunity_master.category_cpc). Denominator of the per-market CPC local modifier on CPL (valuation plan v1 step 2). App-owned so a market_scanner reload cannot wipe it; refreshed by scripts/build_cpc_baseline.py.';

-- RLS on, no policies: only the service_role (which bypasses RLS) reads/writes it,
-- matching the other app-owned LeadOff tables (leadoff_grades, leadoff_spend, …).
alter table public.leadoff_cpc_baseline enable row level security;
