-- Migration: 20260629240000_guides.sql
-- Purpose: In-app Guides portal store. Holds the help/documentation guides (how to
--          use each module, upload SOPs, set clients up) so the team can edit them
--          in-app instead of in code. Seeded from the previously-static content by
--          guide_store.seed_defaults() at app startup (idempotent on slug).
--
-- RLS on, NO client-facing policies (service-role only — the frontend reads/writes
-- through the platform API like every other suite table). Reads are auth-gated,
-- writes admin-gated, in the router.

create table if not exists guides (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,
  title       text not null,
  category    text not null default 'Setup'
                check (category in ('Start here', 'Content', 'Tracking', 'Reporting', 'Setup')),
  icon        text not null default 'BookOpen',
  summary     text not null default '',
  body        text not null default '',
  sort_order  integer not null default 0,
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists idx_guides_enabled on guides (enabled, sort_order);

alter table guides enable row level security;
