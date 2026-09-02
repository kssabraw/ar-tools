-- Local SEO page specs (docs/modules/local-seo-page-spec-plan-v1_0.md §3, Phase 1).
--
-- One kept, versioned JSON spec per client × keyword × location: the page-level
-- word band + per-section min/max bands + structure caps, built from the
-- client's reference layout, the SERP length target and the template's
-- must-haves (services/page_spec.py). Generation consumes it, the page records
-- which version it was written against, and a hand edit sticks (edited_at set)
-- until the user accepts a rebuilt candidate.

create table if not exists local_seo_page_specs (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  -- analysis_cache.cache_key(keyword, location_code, location) — the same key
  -- the SERP analysis is cached under, so spec ↔ analysis line up 1:1.
  spec_key       text not null,
  keyword        text not null,
  location       text not null,
  location_code  int,
  version        int not null default 1,
  spec           jsonb not null,
  -- Set when a human edited this version; an edited spec is never overwritten
  -- by an automatic rebuild (plan §5.6).
  edited_at      timestamptz,
  edited_by      uuid references profiles(id),
  -- Set when a newer version replaced this one; the active spec is the row
  -- with superseded_at null.
  superseded_at  timestamptz,
  created_at     timestamptz not null default now()
);

create index if not exists local_seo_page_specs_active_idx
  on local_seo_page_specs (client_id, spec_key)
  where superseded_at is null;

create index if not exists local_seo_page_specs_history_idx
  on local_seo_page_specs (client_id, spec_key, version desc);

alter table local_seo_page_specs enable row level security;

create policy "authenticated users read local_seo_page_specs"
  on local_seo_page_specs for select
  using (auth.role() = 'authenticated');

comment on table local_seo_page_specs is
  'Versioned Local SEO page spec (length band + per-section min/max + structure caps) per client × keyword × location. Built by services/page_spec.py; consumed by generation; edits stick until a rebuilt candidate is accepted.';

-- The page records the spec it was written against and how it landed, so
-- target vs actual is a column, not a number buried in engine_scores.
alter table local_seo_pages
  add column if not exists page_spec_id  uuid references local_seo_page_specs(id) on delete set null,
  add column if not exists spec_version  int,
  add column if not exists target_words  int,
  add column if not exists actual_words  int,
  add column if not exists length_status text
    check (length_status in ('in_band', 'over_length', 'under_length'));

comment on column local_seo_pages.length_status is
  'Deterministic verdict of the page body vs its spec band: in_band / over_length / under_length (page_spec.length_verdict). Null for pages generated before specs existed.';
