-- Migration: 20260704150000_response_episodes.sql
-- Purpose: Response-episode tracking — the verify loop from the Rank Drop
--          Mitigation SOPs (docs/sops/Rank_Drop_Mitigation_SOP_{Organic,Maps}.md).
--          One episode per drop response: opened when an alert opens, rechecked
--          on the ~2-week cadence ("expect movement ~2 weeks after indexing"),
--          recovered when the alert auto-resolves, and escalated to the Admins
--          after 6 weeks with no improvement ("6-week rule → Kyle/Ryan strategy
--          review"). This is what turns one-shot classified responses into a
--          24/7 loop with a terminal state.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists response_episodes (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  channel         text not null check (channel in ('organic', 'maps')),
  alert_id        uuid not null,           -- rank_alerts.id or maps_alerts.id (by channel)
  keyword_id      uuid,                    -- organic only (tracked_keywords)
  keyword         text not null,
  classification  text,                    -- A / B1–B5 (organic) or the maps alert_type
  status          text not null default 'open'
                    check (status in ('open', 'recovered', 'escalated', 'closed')),
  baseline        jsonb,                   -- metrics at open: {position, impressions, ...}
  checks          jsonb not null default '[]'::jsonb,  -- [{at, verdict, position, note}]
  opened_at       timestamptz not null default now(),
  last_checked_at timestamptz,
  next_check_at   timestamptz,
  recovered_at    timestamptz,
  escalated_at    timestamptz,
  created_at      timestamptz not null default now()
);

-- One open episode per alert (the episode dedup).
create unique index if not exists uq_response_episodes_open_alert
  on response_episodes (alert_id) where status = 'open';
create index if not exists idx_response_episodes_client_status
  on response_episodes (client_id, status, opened_at desc);
create index if not exists idx_response_episodes_due
  on response_episodes (next_check_at) where status = 'open';

alter table response_episodes enable row level security;
