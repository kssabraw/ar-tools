-- Migration: 20260807190000_content_scheduler_drafts.sql
-- Purpose: A durable per-client Content Scheduler DRAFT — the handed-off keyword
--   list a tool (e.g. "Send to Content Scheduler" in Keyword Research) stashes
--   server-side so it survives a refresh / navigation, instead of living only in
--   ephemeral router navigation state. The Content Scheduler batch form seeds
--   from this draft on open and clears it once the batch is created (or the user
--   clears the list). One draft per client (client_id is the PK), so a later
--   hand-off merges into the same pending list.
--
--   This is a draft of the batch INPUT (terms + a suggested page type) — it does
--   not enqueue any generation and the shared scheduler never touches it. Nothing
--   is created until the user picks a page type + cadence and clicks Create /
--   Schedule in the Content Scheduler.
--
-- RLS-on, service-role only (API-layer client_id filtering — suite single-tenant).

create table if not exists content_scheduler_drafts (
  client_id     uuid primary key references clients (id) on delete cascade,
  terms         text[] not null default '{}',
  content_type  text,
  updated_at    timestamptz not null default now()
);

alter table content_scheduler_drafts enable row level security;
