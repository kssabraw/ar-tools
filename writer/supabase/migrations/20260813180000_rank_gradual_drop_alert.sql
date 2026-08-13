-- Migration: 20260813180000_rank_gradual_drop_alert.sql
-- Purpose: Organic Rank Tracker (Module #4) — add the `gradual_drop` alert type.
--
-- The existing rank-drop rules (weekly_drop / thirty_day_drop) only fire on a
-- ≥6-spot fall measured INSIDE a single 7- or 30-day window. A keyword bleeding
-- ~1 position/week never accumulates that fast, so a slow multi-week erosion
-- (e.g. 6 spots over 6 weeks) opened no alert and notified no one — it showed
-- only as a "dropping" status chip nobody is pushed to read.
--
-- `gradual_drop` closes that gap: it measures CUMULATIVE displacement over ~8
-- weeks and fires only when the decline is genuinely gradual (not a sudden
-- cliff the existing rules already own, and suppressed when a weekly/thirty-day
-- drop fires for the same keyword the same run). It rides the same
-- notification + response-episode + Action Plan machinery as the other types.
--
-- Detection lives in services/rank_alerts.py::detect_gradual_drop; this only
-- widens the alert_type CHECK to accept the new value.

alter table rank_alerts drop constraint if exists rank_alerts_alert_type_check;

alter table rank_alerts add constraint rank_alerts_alert_type_check
  check (alert_type in ('weekly_drop', 'page_one_exit', 'thirty_day_drop',
                        'gradual_drop', 'deindexed'));
