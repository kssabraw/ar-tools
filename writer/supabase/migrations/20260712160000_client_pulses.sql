-- Weekly Pulse (owner request 2026-07-12): a short, copy-paste-ready client
-- update ("done last week / on tap this week") generated per client each week
-- and shown as a text block on the client workspace — STAFF deliver it (copy
-- into their own email/message); nothing is auto-sent to clients. Rows are
-- purged after ~2 weeks (pulse_retention_days), so at most the current + prior
-- week exist. One row per client per week (regenerate replaces).

create table if not exists client_pulses (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references clients(id) on delete cascade,
  week_start date not null,          -- the Monday of the "this week" period
  body       text not null,          -- the copyable plain-text update
  created_at timestamptz not null default now(),
  unique (client_id, week_start)
);

create index if not exists idx_client_pulses_client on client_pulses(client_id);

alter table client_pulses enable row level security;
