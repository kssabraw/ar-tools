-- Migration: 20260812020000_local_seo_social_posts.sql
-- Purpose: persist a Local SEO page's generated GBP post suggestions.
--   The page view's "GBP Posts" tab generated suggestions into component state,
--   so navigating away and back re-ran the (paid) generation every time. Store
--   the result on the page so it's generated ONCE and re-read on return; an
--   explicit Regenerate overwrites it. Additive/nullable — older pages have no
--   saved set and generate on first open as before.

alter table local_seo_pages
  add column if not exists social_posts jsonb;
