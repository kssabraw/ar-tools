-- Migration: 20260628022039_serp_snapshot_local_intent.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot.
--          Add local-intent detection to a snapshot. DataForSEO Labs
--          search-intent has no 'local' label (only informational/commercial/
--          transactional/navigational), so local intent is derived from the SERP
--          feature inventory we already capture: a local pack / local finder /
--          map means Google treats the query as locally-intented.
--
-- Additive + backfill-safe: existing snapshots default to false (no local pack
-- recorded ~ not locally-intented); new captures compute it from the SERP.
--
-- RLS already enabled on serp_snapshots (no policy change).

alter table serp_snapshots
  add column if not exists local_intent boolean not null default false;
