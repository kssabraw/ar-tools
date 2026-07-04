-- Migration: 20260704160000_offpage_alerts.sql
-- Purpose: Offpage agent (the detection layer from _ORCHESTRATOR.md §Agents:
--          "Lost referring domains/links · citation status · unnatural RD
--          spikes"). Detects aggregate referring-domain loss and unnatural RD
--          spikes from the backlink_profiles time-series (the interval-gated
--          DataForSEO captures backlink_intel already stores) and feeds the
--          Organic Rank Drop SOP's §A.5 response (loss → replacement plan via
--          the Recipe Engine; spike → negative-SEO / unintended-blast check,
--          MC4 judgment, senior SEO if unclear).
--
--          Same episode semantics as rank_alerts/maps_alerts: at most one OPEN
--          alert per (client, type); resolved_at set when the condition clears.
--          Citation status is deferred — the Citation Audit tool (external)
--          owns citation consistency; the suite has no citation data source.
--
-- RLS on, service-role only (the backend uses the service role key).

create table if not exists offpage_alerts (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid not null references clients(id) on delete cascade,
  alert_type   text not null check (alert_type in ('rd_loss', 'rd_spike')),
  from_rd      integer,                  -- prior capture's referring domains
  to_rd        integer,                  -- latest capture's referring domains
  delta_pct    numeric,                  -- relative change (negative = loss)
  message      text not null,
  details      jsonb,
  status       text not null default 'unread'
                 check (status in ('unread', 'read', 'dismissed')),
  triggered_on date not null default current_date,
  resolved_at  timestamptz,              -- set when the condition clears
  created_at   timestamptz not null default now()
);

-- At most one OPEN alert per client per type (the episode dedup).
create unique index if not exists uq_offpage_alerts_open
  on offpage_alerts (client_id, alert_type)
  where resolved_at is null;
create index if not exists idx_offpage_alerts_client_created
  on offpage_alerts (client_id, created_at desc);

alter table offpage_alerts enable row level security;
