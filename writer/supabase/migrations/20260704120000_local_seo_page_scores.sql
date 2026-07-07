-- Migration: 20260704120000_local_seo_page_scores.sql
-- Purpose: Persist the full 8-engine scoring "verdict" for each Local SEO run.
--          Previously only the composite_score / composite_status / content_gaps
--          survived; the per-engine engine_scores block (each engine's score +
--          issues + recommendations, incl. the deterministic SERP-signal-coverage
--          sub-scores) was computed by nlp-api and then discarded.
--
--          Two pieces (the user chose "both"):
--            1. local_seo_pages.engine_scores — the current verdict for a saved
--               page, co-located with its composite_score.
--            2. local_seo_page_scores — a per-run history log. One row per scoring
--               run: standalone score (page_url, no page row), generate, the
--               reoptimize "before" score, and the reoptimized "after". Enables
--               score-over-time trends and keeps standalone URL scores that never
--               produce a page row.
--
-- RLS on, service-role only (the backend uses the service role key).

-- 1. Current verdict on the saved page row.
alter table local_seo_pages
  add column if not exists engine_scores jsonb;

-- 2. Per-run scoring history.
create table if not exists local_seo_page_scores (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  -- Null for a standalone URL score (no page row) or if the page is later deleted.
  page_id          uuid references local_seo_pages(id) on delete set null,
  keyword          text not null,
  location         text,
  page_url         text,
  -- 'score' (standalone) | 'generate' | 'reoptimize' (after) | 'reoptimize_before'
  mode             text not null
                     check (mode in ('score', 'generate', 'reoptimize', 'reoptimize_before')),
  composite_score  numeric,
  composite_status text,
  engine_scores    jsonb,
  deficiencies     jsonb,
  token_usage      jsonb,
  created_by       uuid,
  created_at       timestamptz not null default now()
);

create index if not exists idx_local_seo_page_scores_client_created
  on local_seo_page_scores (client_id, created_at desc);
create index if not exists idx_local_seo_page_scores_page
  on local_seo_page_scores (page_id, created_at desc);

alter table local_seo_page_scores enable row level security;
