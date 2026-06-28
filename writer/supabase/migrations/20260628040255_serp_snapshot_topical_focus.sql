-- Migration: 20260628040255_serp_snapshot_topical_focus.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot.
--          Record each ranking SITE's topical focus (specialist vs generalist
--          for the keyword's topic) + the keyword's core topic + how many top
--          incumbents are generalists + the client's own focus. A topic
--          specialist can out-rank generalist incumbents even with weaker
--          backlinks, so a generalist-dominated SERP is an opening for a
--          specialist client — a rankability input.
--
-- Classified by a cheap Haiku call at capture time from domain + title + snippet.
-- Additive + best-effort: rows are null when classification didn't run.
--
-- RLS already enabled on both tables (no policy change).

alter table serp_snapshots
  add column if not exists keyword_topic         text,
  add column if not exists generalist_count      integer,   -- # of top incumbents that are generalists
  add column if not exists client_topical_focus  text;      -- specialist | generalist | unknown

alter table serp_snapshot_results
  add column if not exists topical_focus text;              -- specialist | generalist | unknown
