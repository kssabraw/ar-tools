-- Migration: 20260628032756_serp_snapshot_targeted.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot.
--          Record whether each ranking page is written *for* the targeted
--          keyword (title/URL-slug token coverage), and how many of the top
--          organic results are. Many loosely-relevant incumbents = a gap a
--          purpose-built page can take — a rankability input.
--
-- Derived for free from data already captured (title + URL). Additive +
-- backfill-safe: existing rows are null (the frontend mirrors the heuristic for
-- snapshots captured before these columns existed).
--
-- RLS already enabled on both tables (no policy change).

alter table serp_snapshots
  add column if not exists targeted_count integer;   -- # of top-N organic results written for the keyword

alter table serp_snapshot_results
  add column if not exists targeted boolean;          -- this page is written for the keyword
