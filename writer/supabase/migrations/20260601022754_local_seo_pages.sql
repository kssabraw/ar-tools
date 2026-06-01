-- Migration: 20260601022754_local_seo_pages.sql
-- Purpose: Local SEO module (#2) — store generated local SEO pages per client.
-- Ports ShowUP Local's `generated_pages`, re-keyed to the suite `clients` table.
-- See docs/modules/local-seo-module-integration-plan-v1_0.md (Phase 1).

create table local_seo_pages (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients(id) on delete cascade,
  keyword           text not null,
  location          text not null,
  -- Whether competitor SERP analysis was run for this generation (the
  -- user's explicit per-page choice; see plan §2). Stored for provenance.
  run_analysis      boolean not null default false,
  content_html      text not null default '',
  schema_json       text not null default '',
  page_title        text,
  content_gaps      jsonb not null default '[]'::jsonb,
  composite_score   numeric(5, 2),
  composite_status  text,
  -- 'generate' (fresh) or 'reoptimize' (rewritten to lift the score).
  mode              text not null default 'generate'
                      check (mode in ('generate', 'reoptimize')),
  token_usage       jsonb,
  cost_breakdown    jsonb,
  created_by        uuid references profiles(id),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index local_seo_pages_client_id_idx
  on local_seo_pages (client_id, created_at desc);

-- RLS — match the suite convention (backend uses the service-role key and
-- bypasses these; policies gate anon/authenticated access). Mirrors `runs`.
alter table local_seo_pages enable row level security;

create policy "authenticated users read local_seo_pages"
  on local_seo_pages for select
  using (auth.role() = 'authenticated');

create policy "authenticated users create local_seo_pages"
  on local_seo_pages for insert
  with check (auth.role() = 'authenticated');

create policy "creators and admins update local_seo_pages"
  on local_seo_pages for update
  using (
    created_by = auth.uid()
    or exists (select 1 from profiles where profiles.id = auth.uid() and profiles.role = 'admin')
  );
