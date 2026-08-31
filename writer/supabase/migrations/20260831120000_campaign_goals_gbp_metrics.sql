-- Migration: 20260831120000_campaign_goals_gbp_metrics.sql
-- Purpose: Extend campaign goals with GBP performance targets and a percentage
--          target mode.
--   * Three new goal_types measured from gbp_metric_daily (30-day trailing sum,
--     summed across the client's verified GBP locations):
--       - gbp_calls          → CALL_CLICKS
--       - gbp_impressions     → the four BUSINESS_IMPRESSIONS_* sub-types folded
--                               into one "profile views" total
--       - gbp_website_clicks  → WEBSITE_CLICKS
--   * target_mode lets a volume goal ("increase impressions / GBP calls / …")
--     be expressed as an absolute number (default) OR a percentage increase
--     over the captured baseline. For percent_increase, target_value is the %
--     and the effective absolute target = baseline_value * (1 + target_value/100),
--     computed deterministically on read (services/campaign_goals.py) — nothing
--     new is stored.

alter table campaign_goals drop constraint if exists campaign_goals_goal_type_check;

alter table campaign_goals add constraint campaign_goals_goal_type_check
  check (goal_type in (
    'keyword_position',     -- one keyword to position <= target_value
    'keywords_in_top',      -- target_value keywords at position <= target_position
    'organic_clicks',       -- GSC clicks / 30 days >= target
    'organic_impressions',  -- GSC impressions / 30 days >= target
    'ai_visibility',        -- AI-answer visibility pct >= target
    'maps_pack_presence',   -- geo-grid top-3 pin share pct >= target
    'gbp_calls',            -- GBP call clicks / 30 days >= target
    'gbp_impressions',      -- GBP profile views (folded) / 30 days >= target
    'gbp_website_clicks',   -- GBP website clicks / 30 days >= target
    'custom'                -- free-text goal, no auto-measurement
  ));

alter table campaign_goals
  add column if not exists target_mode text not null default 'absolute'
    check (target_mode in ('absolute', 'percent_increase'));
