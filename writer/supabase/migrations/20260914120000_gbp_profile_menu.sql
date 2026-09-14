-- GBP Profile Editor — add the `menu` field (a first-class "Menu link" URL card,
-- backed by the Business Information v1 `attributes/url_menu` URL attribute).
--
-- `menu` is an attribute-backed field: like `attributes`, it is written through
-- the separate getAttributes/updateAttributes endpoint pair (NOT locations.patch),
-- but it presents to the operator as a single URL string. It reuses the existing
-- `gbp_profile_edits` row + apply job (re-read-and-diff) + reconciler + freeze
-- gate + history — this migration only widens the field CHECK.
--
-- The CHECK is rebuilt from the LIVE constraint set (verified 2026-09-14) + 'menu'
-- (the repo pattern: the live set can be wider than any single migration file).
-- See docs/modules/gbp-profile-editor/HANDOFF.md.

alter table public.gbp_profile_edits
  drop constraint if exists gbp_profile_edits_field_check;

alter table public.gbp_profile_edits
  add constraint gbp_profile_edits_field_check
  check (field in (
    'description', 'hours', 'services', 'website', 'labels', 'special_hours',
    'more_hours', 'service_area', 'open_info', 'categories', 'attributes', 'menu'
  ));
