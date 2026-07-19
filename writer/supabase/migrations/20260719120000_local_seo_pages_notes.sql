-- Migration: 20260719120000_local_seo_pages_notes.sql
-- Purpose: Persist the per-page writing Notes on the local SEO page row, matching
--          ecommerce_pages.notes. The note already reaches the writer (threaded
--          via the Content Scheduler / single-page generate), but was not stored
--          on the produced page, losing provenance. Additive, nullable.

alter table local_seo_pages
  add column if not exists notes text;
