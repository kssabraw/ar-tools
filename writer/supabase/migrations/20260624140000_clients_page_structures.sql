-- Migration: 20260624140000_clients_page_structures.sql
-- Purpose: Per-client "reference page structures" so the writing modules can
-- mirror each client's existing page layouts. Stores four reference page URLs
-- (local landing, service, location, blog post) plus the scraped + analyzed
-- structure of each (a heading outline + a natural-language summary, chrome
-- stripped). Captured once and kept indefinitely; re-analyzed when a URL
-- changes (mirrors the website_scrape flow).
--
-- Storage shape (single JSONB column, keyed by page type):
--   {
--     "local_landing": {
--       "url": "https://…",
--       "status": "pending" | "complete" | "failed" | "empty",
--       "error": null | "…",
--       "analysis": { "outline": [...], "summary": "…", ... } | null,
--       "analyzed_at": "2026-06-24T…Z" | null
--     },
--     "service":  { … },
--     "location": { … },
--     "blog_post":{ … }
--   }
-- An absent key means no URL has been configured for that page type.

alter table clients
  add column if not exists page_structures jsonb not null default '{}'::jsonb;

-- Freeze the reference structures into each run's client-context snapshot
-- (mirrors website_analysis) so a run mirrors the structures as they were when
-- it started.
alter table client_context_snapshots
  add column if not exists page_structures jsonb not null default '{}'::jsonb;

-- Allow the new async job that scrapes + analyzes a single reference page.
alter table public.async_jobs
  drop constraint if exists async_jobs_job_type_check;

alter table public.async_jobs
  add constraint async_jobs_job_type_check check (
    job_type = any (array[
      'website_scrape', 'silo_dedup', 'gsc_ingest', 'gsc_materialize',
      'dataforseo_rank', 'keyword_market', 'gsc_page_ingest', 'rank_report',
      'serp_snapshot', 'maps_scan', 'maps_report', 'page_structure_scrape'
    ])
  );
