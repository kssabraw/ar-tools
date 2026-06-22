-- Migration: 20260622150000_local_seo_pages_published.sql
-- Purpose: Local SEO module (#2) — track publishing a generated page to a Google
-- Doc in the client's Drive folder (via the existing Apps Script webhook, the
-- same path the blog writer uses). Stores the resulting Doc id/url + timestamp.

alter table local_seo_pages
  add column if not exists published_doc_id  text,
  add column if not exists published_doc_url text,
  add column if not exists published_at      timestamptz;
