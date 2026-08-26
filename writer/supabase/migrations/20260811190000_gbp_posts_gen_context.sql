-- Migration: 20260811190000_gbp_posts_gen_context.sql
-- Purpose: per-post "Regenerate" for AI-drafted GBP posts.
--   Stores the small generation context a post was drafted from (topic type,
--   theme/angle, source page URL, and its slot within a bulk batch) so a single
--   post can be re-drafted faithfully — a URL-generated post re-fetches its page
--   and keeps its distinct angle. The (large) page content is NOT stored; it is
--   re-fetched on demand. Best-effort/additive: null for older posts and for
--   manually-authored posts, which simply can't be regenerated.
--   The AI image prompt rides the existing `media` jsonb ([{sourceUrl, prompt}]),
--   so image regeneration needs no schema change.

alter table gbp_posts
  add column if not exists gen_context jsonb;
