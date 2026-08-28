-- Autonomous SEO agent — Phase 2 data foundations (autonomous-seo-agent-plan-v1_0.md §5).
-- Inert until the executor (Phase 3) is built AND autonomy_enabled flips true.
-- Nothing here changes existing behaviour: a new column defaulting to 0 (off),
-- a per-client monthly spend meter + its atomic reservation RPC, and an audit
-- ledger the executor will write. RLS on, service-role only (suite model).

-- Per-client opt-in tier: 0 = off (today's fully-human behaviour), 1 = owned &
-- reversible, 2 = drafts + owned content, 3 = auto-publish (held for a later
-- decision). Default 0, so every existing client is unchanged.
alter table clients
  add column if not exists autonomy_tier smallint not null default 0;

-- Per-client, per-month autonomous spend meter. The month is the first day of
-- the calendar month (UTC). Mirrors the keyword_research_usage / leadoff_spend
-- pattern, but keyed by client (autonomous budgets are per-client, not global).
create table if not exists autonomy_spend (
  client_id  uuid not null references clients (id) on delete cascade,
  month      date not null,
  spent_usd  numeric not null default 0,
  primary key (client_id, month)
);

alter table autonomy_spend enable row level security;

-- Atomic check-and-increment: reserve p_amount against the client's monthly cap.
-- Returns true only if the reservation fit under the cap (the row was updated),
-- mirroring reserve_keyword_research_calls. A refused reservation leaves spend
-- unchanged, so the executor falls back to PROPOSING rather than spending.
create or replace function reserve_autonomy_spend(
  p_client uuid, p_month date, p_amount numeric, p_cap numeric
)
returns boolean
language plpgsql
as $$
begin
  insert into autonomy_spend (client_id, month, spent_usd)
    values (p_client, p_month, 0)
    on conflict (client_id, month) do nothing;
  update autonomy_spend
     set spent_usd = spent_usd + p_amount
   where client_id = p_client
     and month = p_month
     and spent_usd + p_amount <= p_cap;
  return found;
end;
$$;

-- The audit ledger: one row per autonomy_run, recording the goal snapshot it
-- acted on, the per-proposal policy decisions, what it commissioned, and the
-- cost. Written by the Phase 3 executor; created now so the foundation is in
-- place and the daily "what I did & why" digest has a source.
create table if not exists autonomy_runs (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  trigger        text not null default 'scheduled',
  tier           smallint not null default 0,
  goal_snapshot  jsonb,
  decisions      jsonb,
  actions_taken  jsonb,
  cost_usd       numeric not null default 0,
  created_at     timestamptz not null default now()
);

create index if not exists autonomy_runs_client_idx
  on autonomy_runs (client_id, created_at desc);

alter table autonomy_runs enable row level security;
