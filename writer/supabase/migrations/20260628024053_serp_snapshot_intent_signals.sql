-- Migration: 20260628024053_serp_snapshot_intent_signals.sql
-- Purpose: Organic Rank Tracker (Module #4) — Competitive SERP Snapshot.
--          Persist a normalized set of derived intent signals per snapshot.
--          Google's SERP composition is itself an intent classification: the
--          features it shows (discussions & forums, video, news, shopping,
--          featured snippet, PAA, knowledge panel, images, recipes/jobs/events)
--          plus content-format patterns in the organic titles (listicle,
--          comparison, how-to, freshness, definitional) and a navigational read
--          when homepages dominate. Derived for free from data already captured.
--
-- Additive + backfill-safe: existing snapshots have null (the frontend mirrors
-- the derivation client-side for them); new captures store the computed list.
--
-- RLS already enabled on serp_snapshots (no policy change).

alter table serp_snapshots
  add column if not exists intent_signals jsonb;
