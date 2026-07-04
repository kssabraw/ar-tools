-- Migration: 20260705120000_strategy_reviews_published_doc.sql
-- Purpose: Let a completed SerMaStr strategy review be published as an INTERNAL
--          Google Doc in the client's Drive folder (services/strategy_report.py).
--          Store the resulting doc link so the UI can show "already saved · open
--          doc" instead of re-publishing. Strictly additive (nullable columns).

alter table strategy_reviews
  add column if not exists published_doc_id  text,
  add column if not exists published_doc_url text,
  add column if not exists published_at      timestamptz;
