-- GBP Profile Editor — Phase 3b (part 1): add the `categories` editable field.
-- Categories ride the same v1 locations.patch endpoint as the Tier-A fields
-- (updateMask=categories), but the editor needs a live category-catalog search
-- (categories.list) to pick valid gcids, and changing the PRIMARY category is
-- gated behind an extra confirm in the UI (it shifts ranking behaviour).
--
-- This only relaxes the field CHECK. The live constraint already carries the
-- 3a values (description/hours/services + website/labels/special_hours/
-- more_hours/service_area/open_info, migration 20260909120000); add 'categories'.
-- `attributes` is the other 3b field but uses a SEPARATE endpoint pair
-- (getAttributes/updateAttributes) — it lands in its own migration + PR.

ALTER TABLE gbp_profile_edits DROP CONSTRAINT IF EXISTS gbp_profile_edits_field_check;

ALTER TABLE gbp_profile_edits ADD CONSTRAINT gbp_profile_edits_field_check CHECK (
  field = ANY (ARRAY[
    'description', 'hours', 'services',
    'website', 'labels', 'special_hours', 'more_hours', 'service_area', 'open_info',
    'categories'
  ])
);
