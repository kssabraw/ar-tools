-- GBP Profile Editor — Phase 3a: widen the editable-field set beyond the original
-- three (description / hours / services) to the full Tier-A set that rides the same
-- v1 locations.patch endpoint, one field per updateMask:
--   website        — websiteUri (a plain URL)
--   labels         — the listing's internal labels (List[str], <=10, <=255 each)
--   special_hours  — holiday / one-off hours (specialHours)
--   more_hours     — additional hours per type (moreHours: kitchen / delivery / …)
--   service_area   — a service-area business's coverage (serviceArea)
--   open_info      — open / closed-temporarily / closed-permanently (openInfo)
--
-- Every new field rides the existing gbp_profile_edits row + apply job
-- (re-read-and-diff) + gbp_profile_sync reconciler + freeze gate unchanged — this
-- migration only relaxes the field CHECK. The NAP identity triplet
-- (title / address / phone) stays OUT of the tool (ADR 0005). Media (photos/logo/
-- cover, the v4 API) is Phase 3c and does NOT ride this field column.
--
-- The live CHECK is exactly the original three (verified 2026-09-09); drop + rebuild.

ALTER TABLE gbp_profile_edits DROP CONSTRAINT IF EXISTS gbp_profile_edits_field_check;

ALTER TABLE gbp_profile_edits ADD CONSTRAINT gbp_profile_edits_field_check CHECK (
  field = ANY (ARRAY[
    'description', 'hours', 'services',
    'website', 'labels', 'special_hours', 'more_hours', 'service_area', 'open_info'
  ])
);
