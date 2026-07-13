-- Migration: 20260713060000_keyword_research_reports.sql
-- Purpose: Keyword Research module — client-facing PDF report history.
--   Each row is one generated report for a keyword_research_runs run: a
--   white-label PDF stored in the private `reports` bucket (storage_path, signed
--   on read) and, when the client has a Drive folder, uploaded there too
--   (drive_url). Mirrors fanout.keyword_reports / client_reports.
--
-- RLS-on, service-role only (API-layer client_id filtering — suite single-tenant).

create table if not exists keyword_research_reports (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients (id) on delete cascade,
  run_id        uuid not null references keyword_research_runs (id) on delete cascade,
  title         text,
  status        text not null default 'complete',
  storage_path  text,
  drive_url     text,
  created_by    uuid,
  created_at    timestamptz not null default now()
);

create index if not exists keyword_research_reports_client_idx
  on keyword_research_reports (client_id, created_at desc);

alter table keyword_research_reports enable row level security;
