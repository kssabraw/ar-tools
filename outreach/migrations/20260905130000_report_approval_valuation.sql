-- =============================================================================
-- report_approval.valuation — freeze the valuation snapshot at approval (Phase B)
--
-- Phase B of the missed-opportunity valuation (docs/missed-opportunity-valuation-
-- prd-v0_1.md): the approval-gated client PDF carries a dollar figure, so that
-- figure must be REPLAYABLE.
--
-- The approved PDF's exact bytes are ALREADY frozen — content_hash is the sha256 of
-- the approved HTML and the PDF is stored at {prospect_id}/{content_hash}.pdf — so
-- the OUTPUT the prospect saw is immutable. This column additionally freezes the
-- INPUTS the figure was computed from (search volume, CPC, location_token, the
-- Census downscale ratio, the CTR-curve + category-default the compute used, any
-- override) as they stood at approval time, so we can always answer "what numbers
-- produced the figure this prospect saw" — the score_factors replayability
-- discipline, applied to a client-facing claim.
--
-- NULL for an approval that carried no valuation (feature off, or no dollar figure
-- was available at approval — unknown ≡ absent, never a fabricated zero).
--
-- Two databases, two migration dirs: this is the Outreacher project, never
-- writer/supabase/migrations.
-- =============================================================================

alter table report_approval add column if not exists valuation jsonb;

comment on column report_approval.valuation is
  'Frozen missed-opportunity valuation snapshot (inputs + outputs) at approval time — the replayable '
  'record of the dollar figure the approved client PDF carried (docs/missed-opportunity-valuation-'
  'prd-v0_1.md Phase B). The content_hash + stored PDF freeze the OUTPUT bytes; this freezes the '
  'INPUTS so the figure can be re-derived/audited. NULL when the approval carried no valuation.';
