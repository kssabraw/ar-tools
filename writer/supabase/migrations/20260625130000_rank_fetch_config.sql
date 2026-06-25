-- Migration: 20260625130000_rank_fetch_config.sql
-- Purpose: Organic Rank Tracker (Module #4) — per-client rank-DATA refresh
--          schedule. Until now the DataForSEO live-rank pull fired weekly on a
--          single GLOBAL weekday (config.dataforseo_rank_weekday) for every
--          client. This lets each client choose its own cadence (a chosen
--          weekday, a day of the month, every N days, or off/manual-only) so the
--          team can, e.g., track low-priority clients monthly to bound cost.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md.
--
-- Mirrors rank_report_config (20260622214725). One row per client; absent = the
-- legacy default (weekly on the global weekday), so existing clients are
-- unchanged until a schedule is explicitly set.
--
-- RLS on, no client-facing policies (service-role only).

create table if not exists rank_fetch_config (
  client_id       uuid primary key references clients(id) on delete cascade,
  mode            text not null default 'weekly'
                    check (mode in ('off', 'weekly', 'monthly', 'interval')),
  day_of_week     integer check (day_of_week between 0 and 6),   -- weekly (0=Mon)
  day_of_month    integer check (day_of_month between 1 and 31), -- monthly
  interval_days   integer check (interval_days > 0),             -- every N days
  last_fetched_at timestamptz,                                   -- advanced on each actual fetch
  updated_at      timestamptz not null default now()
);

alter table rank_fetch_config enable row level security;
