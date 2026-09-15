-- Migration: 20260916140000_google_trends_social_lane.sql
-- Purpose: the "Trending / social" lane (issue #1129, Phase A).
--   A rising query with no Ads search volume (qualified=false) is often an
--   EMERGING term too new to have measured volume yet — the trend-jacking signal
--   for SOCIAL / short-form content, not SEO. The module already KEEPS these rows
--   (flagged qualified=false); this tags them so they can be surfaced + ranked in
--   their own lane instead of being dead weight.
--
--   Per-keyword classifier outputs (services/google_trends_social.py), tagged on
--   the UNQUALIFIED rows only:
--     * social_lean      — 'social' | 'seo' | 'ambiguous' (from the query text)
--     * suggested_format — 'short-form video' | 'before/after video' | 'meme' | ...
--     * social_score     — velocity × lean weight; the lane's sort key (trend_score
--                          is ~0 for a no-volume row, so it can't be used here)
--
-- All additive + nullable (old rows read as NULL → not in the social lane). Ships
-- inert until the classifier runs on new scans; gated by google_trends_enabled +
-- google_trends_social_classify_enabled.

alter table google_trends_keywords add column if not exists social_lean text;
alter table google_trends_keywords add column if not exists suggested_format text;
alter table google_trends_keywords add column if not exists social_score numeric;
