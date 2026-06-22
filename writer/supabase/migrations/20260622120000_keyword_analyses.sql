-- Migration: 20260622120000_keyword_analyses.sql
-- Purpose: cache the expensive SERP analysis (DataForSEO + ScrapeOwl + TextRazor)
-- so /analyze, Score-My-Page, and run_analysis generation reuse a recent result
-- instead of re-scraping ~20 competitor pages every time.
-- SERP analysis depends only on (keyword, location) — NOT the client — so entries
-- are shared across all clients. See docs/modules SERP analysis PRD §7 (caching).

create table keyword_analyses (
  id             uuid primary key default gen_random_uuid(),
  -- Normalized "<keyword>::<location_code|location_name>" — the shared cache key.
  cache_key      text not null unique,
  keyword        text not null,
  location_code  integer,
  location_name  text,
  -- Full AnalysisResponse JSON (serp_urls, related_keywords, entities, etc.).
  analysis       jsonb not null,
  created_at     timestamptz not null default now()
);

create index keyword_analyses_created_at_idx on keyword_analyses (created_at desc);

-- RLS: this is an internal cache touched only by the platform-api service-role
-- key (which bypasses RLS). No policies → anon/authenticated have no direct
-- access by design. Enabled to avoid an "RLS disabled" advisory.
alter table keyword_analyses enable row level security;
