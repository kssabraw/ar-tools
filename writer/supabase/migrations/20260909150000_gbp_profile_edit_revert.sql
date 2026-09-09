-- GBP Profile Editor — revert support. The prior value of every field is already
-- on file: each gbp_profile_edits row keeps `current_value` (the re-read-and-diff
-- baseline snapshotted at draft time; on a SUCCESSFULLY applied edit it is exactly
-- the value that was live immediately before the patch, since apply aborts into
-- `live_changed` if the value drifted). "Revert" therefore stages a NEW draft
-- whose proposed_value is an applied edit's `current_value`, which an operator
-- then applies through the normal reviewed pipeline — never auto-applied
-- (ADR 0004: a revert is still a persistent, customer-facing write; re-read-and-diff
-- protects it exactly as it protects any other apply).
--
-- Two additions:
--   1. a 'revert' edit source (so the change trail can label a revert distinctly),
--   2. reverts_edit_id → the applied edit this one restores (the audit link;
--      ON DELETE SET NULL — the revert stands on its own if the original is purged).

-- Rebuild the source CHECK preserving the live values + add 'revert'.
ALTER TABLE gbp_profile_edits DROP CONSTRAINT IF EXISTS gbp_profile_edits_source_check;

ALTER TABLE gbp_profile_edits ADD CONSTRAINT gbp_profile_edits_source_check CHECK (
  source = ANY (ARRAY['manual', 'ai', 'strategist', 'revert'])
);

ALTER TABLE gbp_profile_edits
  ADD COLUMN IF NOT EXISTS reverts_edit_id uuid
    REFERENCES gbp_profile_edits(id) ON DELETE SET NULL;
