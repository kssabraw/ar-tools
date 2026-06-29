-- Migration: 20260629120000_brand_response_analysis.sql
-- Purpose: AI Visibility module (Brand Strength) — richer per-cell response
--   analysis. Adds one JSONB column to brand_mention_history holding the
--   structured signals mined from each engine's answer beyond the binary
--   found/not-found bit:
--     - position:   {rank, total_businesses}  — share-of-voice, not just presence
--     - prominence: 'leading' | 'passing' | 'caveated' | null (quality of mention)
--     - sources:    cited-domain classification (directory/review/social/editorial/
--                   own/competitor), whether the client's own site was cited,
--                   and which sources cite competitors but not the client
--     - discovered_competitors: businesses the answer named that aren't tracked
--     - competitor_attributes:  the reasons/attributes the answer gives each
--                               ranked business (the AEO themes that win)
--     - accuracy_flags: facts the AI stated about the brand that disagree with GBP
--     - intent:      {inferred, locations}    — how the AI read the query
--     - aio:         {mention_kind} for Google AI Overview / AI Mode —
--                    'none' | 'citation_only' | 'in_content_link' | 'both'
--                    (an inline content link carries more weight than a bare
--                     entry in the sources strip)
--
-- One JSONB column (vs many scalar columns) keeps the migration narrow and lets
-- the analysis schema evolve without further migrations. Computed at scan time
-- by services/brand_analysis.py; null on rows scanned before this change.

alter table brand_mention_history
  add column if not exists response_analysis jsonb;
