-- GBP Profile Editor — Phase 3b (part 2): add the `attributes` editable field.
--
-- UNLIKE every other editable field, attributes do NOT ride v1 locations.patch:
-- they live on a SEPARATE endpoint pair — locations.getAttributes /
-- locations.updateAttributes (an Attributes resource keyed at
-- locations/{id}/attributes) — with a per-attribute updateMask, category-scoped
-- availability (attributes.list), and value-typed values (BOOL/ENUM/URL/
-- REPEATED_ENUM). The gbp_profile_edits row + apply job (re-read-and-diff) +
-- gbp_profile_sync reconciler + freeze gate are reused, but the service layer
-- branches the read/write for attributes onto that endpoint pair.
--
-- This only relaxes the field CHECK (adds 'attributes' to the existing 3a+3b set:
-- description/hours/services + website/labels/special_hours/more_hours/
-- service_area/open_info + categories, migrations 20260909120000 / 130000). The
-- NAP identity triplet (title/address/phone) stays OUT of the tool (ADR 0005);
-- media (photos/logo/cover, the v4 API) is Phase 3c and does NOT ride this column.

ALTER TABLE gbp_profile_edits DROP CONSTRAINT IF EXISTS gbp_profile_edits_field_check;

ALTER TABLE gbp_profile_edits ADD CONSTRAINT gbp_profile_edits_field_check CHECK (
  field = ANY (ARRAY[
    'description', 'hours', 'services',
    'website', 'labels', 'special_hours', 'more_hours', 'service_area', 'open_info',
    'categories', 'attributes'
  ])
);
