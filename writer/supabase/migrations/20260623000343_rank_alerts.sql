-- Migration: 20260623000343_rank_alerts.sql
-- Purpose: Organic Rank Tracker (Module #4) — in-app rank-drop ALERTS (M4's
--          remaining piece). First slice of the suite notifications service,
--          scoped to rank alerts and delivered IN-APP only (email stays
--          deferred until the notifications service proper).
--
-- Alert types (computed daily in the materialize job, per keyword, on the
-- keyword's PRIMARY source — GSC avg position where covered, else DataForSEO
-- weekly rank; never reconciling the two):
--   - weekly_drop      : was ranking in spots 1–15, dropped ≥6 spots in a week
--   - page_one_exit    : was on page 1 (≤10), now off it (>10)
--   - thirty_day_drop  : was in ~top 20, dropped ≥6 spots over 30 days
--   - deindexed        : sustained NULL GSC days after an established baseline
--                        (reuses the existing deindex_risk signal; GSC-only)
--
-- Episode model: at most ONE *open* (unresolved) alert per (keyword, type).
-- A new alert is created when the condition first holds; it is auto-resolved
-- (resolved_at set) once the condition clears. status is the user's read-state.
--
-- RLS on, NO client-facing policies (service-role only) — the async_jobs pattern.

create table if not exists rank_alerts (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients(id) on delete cascade,
  keyword_id    uuid not null references tracked_keywords(id) on delete cascade,
  keyword       text not null,
  alert_type    text not null
                  check (alert_type in ('weekly_drop', 'page_one_exit',
                                        'thirty_day_drop', 'deindexed')),
  source        text,                      -- 'gsc' | 'dataforseo' (rank that drove it)
  from_position numeric,                   -- baseline position (null for deindexed)
  to_position   numeric,                   -- current position (null if gone/deindexed)
  delta         numeric,                   -- to − from (positive = worse); null for deindexed
  message       text not null,
  details       jsonb,
  status        text not null default 'unread'
                  check (status in ('unread', 'read', 'dismissed')),
  triggered_on  date not null default current_date,
  resolved_at   timestamptz,               -- set when the condition clears (recovery)
  read_at       timestamptz,
  dismissed_at  timestamptz,
  created_at    timestamptz not null default now()
);

-- At most one OPEN alert per keyword per type (the episode dedup).
create unique index if not exists uq_rank_alerts_open
  on rank_alerts (keyword_id, alert_type)
  where resolved_at is null;

create index if not exists idx_rank_alerts_client_status
  on rank_alerts (client_id, status);
create index if not exists idx_rank_alerts_client_created
  on rank_alerts (client_id, created_at desc);

alter table rank_alerts enable row level security;
