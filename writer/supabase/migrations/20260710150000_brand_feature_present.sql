-- AI Visibility: flag scan cells where the Google AI feature (AI Overview /
-- AI Mode) did not fire for the query. A feature that never appeared is not a
-- "miss", so these cells are excluded from the visibility score + health score
-- (the rollups in brand_service.compute_trends / brand_report_html.aggregate_range
-- / brand_alerts.index_batch skip feature_present = false).
--
-- Default true = present/applicable — covers every non-AIO engine and all
-- historical rows; only the DataForSEO Google AI engines ever set it false.
alter table brand_mention_history
  add column if not exists feature_present boolean not null default true;

-- Backfill historical AIO / AI-Mode cells that recorded the deterministic
-- "no AI answer was displayed" synthetic response as not-present.
update brand_mention_history
   set feature_present = false
 where engine in ('google_ai_overview', 'google_ai_mode')
   and coalesce(mention_found, false) = false
   and raw_response ilike 'No Google % was displayed for the query%';
