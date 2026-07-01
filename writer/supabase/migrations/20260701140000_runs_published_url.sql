-- Migration: 20260701140000_runs_published_url.sql
-- Purpose: persist the WordPress/site publish URL on runs (blog / service /
--          location pages), mirroring published_doc_url. Until now only the
--          Google Doc URL was stored; the WP post link was returned to the
--          caller but never written back, so a "published to website" badge on
--          the content lists had no durable source. Additive + nullable.

alter table runs add column if not exists published_url text;
