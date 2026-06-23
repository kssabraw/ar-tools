-- Pre-publish ranking check (per client). Before a client accepts the final
-- content map, surface whether they already rank top-10 for each planned
-- article's target keyword (GSC first, DataForSEO SERP fallback).
-- Applied to prod via Supabase MCP on 2026-06-23.

-- Persisted per-keyword result on the session so the cluster/architecture review
-- renders badges without re-fetching:
--   { as_of, status, checked, ranked,
--     results: [{ cluster_id, keyword, ranked, position, url, source }] }
-- Short TTL in app logic — rankings drift.
alter table fanout.sessions
  add column if not exists prepublish_rank_check jsonb;

-- The user's per-article decision derived from the check: skip the article, or
-- refresh the existing ranking page instead of commissioning a new one.
alter table fanout.clusters
  add column if not exists prepublish_action text
  check (prepublish_action in ('skip', 'refresh'));
