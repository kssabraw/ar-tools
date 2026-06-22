-- Migration: 20260622220000_keyword_index_status.sql
-- Purpose: Organic Rank Tracker (Module #4) — deindex confirmation.
--          Store the GSC URL Inspection result for a keyword's canonical page,
--          so a `deindex_risk` status can be confirmed as "this page is
--          deindexed" rather than just "rankings look low" (PRD §7).
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §4, §7.

alter table tracked_keywords add column if not exists index_status text
  check (index_status in ('indexed', 'not_indexed', 'unknown'));
alter table tracked_keywords add column if not exists index_coverage text;
alter table tracked_keywords add column if not exists index_checked_at timestamptz;
