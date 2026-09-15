-- Migration: 20260916120000_google_trends_phases234.sql
-- Purpose: schema deltas for Google Trends Discovery Phases 2-4 (continue).
--   Phase 2 (informational, category scan): a scan `mode` + the relevance/audience
--     gate outputs on each rising query (so a category scan's gated set is inspectable).
--   Phase 3 (portfolio sweep): the agency-wide weekly run has NO client scope, so
--     google_trends_runs.client_id must be nullable; `mode='portfolio'` marks it and
--     source_client_name attributes each rising query to the client whose seed
--     surfaced it.
--   Phase 4 (local seasonal): no new table — the seasonality profile + outlook ride
--     the async_jobs row (like backlink_lookup). Only `mode='local_seasonal'` here.
--
-- All additive + idempotent. Ships dark behind settings.google_trends_enabled.

-- Portfolio runs are client-less.
alter table google_trends_runs alter column client_id drop not null;

-- Scan mode (keyword=Phase 1 | category=Phase 2 | portfolio=Phase 3 | local_seasonal=Phase 4).
alter table google_trends_runs add column if not exists mode text not null default 'keyword';

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'google_trends_runs_mode_check'
  ) then
    alter table google_trends_runs add constraint google_trends_runs_mode_check
      check (mode = any (array['keyword', 'category', 'portfolio', 'local_seasonal']));
  end if;
end $$;

-- Phase 2 gate outputs + Phase 3 attribution on each rising query.
alter table google_trends_keywords add column if not exists relevance_score numeric;
alter table google_trends_keywords add column if not exists audience_fit text;
alter table google_trends_keywords add column if not exists source_client_name text;
