-- Migration: 20260621120000_clients_brand_voice.sql
-- Purpose: Suite-wide structured brand voice as a single client-level asset.
--
-- Re-adds the "brand voice" capability that the Local SEO integration plan cut
-- from v1 (client-site brand-voice scraping), now CONVERGED per the Option-A
-- decision: a structured `brand_voice` JSONB becomes the canonical store, used
-- by BOTH consumers —
--   * Local SEO (nlp-api) reads the structured VoiceProfile directly;
--   * the Blog Writer keeps reading free text, which we render from brand_voice
--     into its run snapshot's `brand_guide_text` (no Writer pipeline change).
--
-- Provenance lives in `brand_voice.source` ('user' | 'app'): a user-authored
-- voice supersedes and blocks auto-scan overwrite (unless force-rescanned).
--
-- Existing hand-written `brand_guide_text` is preserved by seeding it as a
-- user-authored block (source:'user', raw_text passthrough) so nothing is lost
-- and manual input continues to supersede after convergence.

alter table clients add column if not exists brand_voice jsonb;

comment on column clients.brand_voice is
  'Structured brand voice (converged, Option A). Shape: { source: user|app, '
  'raw_text, current_voice, recommended_voice, recommended_accepted, '
  'writer_execution_guide, generated_at, edited_at }. Canonical for the suite; '
  'rendered into the Blog Writer run snapshot brand_guide_text.';

-- Seed: preserve any existing free-text brand guide as a user-authored voice.
update clients
set brand_voice = jsonb_build_object(
      'source',                 'user',
      'raw_text',               brand_guide_text,
      'current_voice',          null,
      'recommended_voice',      null,
      'recommended_accepted',   null,
      'writer_execution_guide', null,
      'generated_at',           null,
      'edited_at',              to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    )
where coalesce(brand_guide_text, '') <> ''
  and brand_voice is null;
