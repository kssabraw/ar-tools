-- Add a `neighborhood` column to the reverse-geocode cache.
--
-- In a mega-city the `locality` (city) is the whole city — "New York" for every
-- borough — so the LeadOff GBP Placement Advisor's zones all named to
-- "Near New York". The neighborhood/borough (sublocality / neighborhood address
-- component) is what makes the placements distinct + legible ("serve Astoria",
-- not "Near New York" ×4). Additive + nullable: the existing `city`/`admin_area`
-- reads are unchanged, older cached rows keep NULL until they are re-geocoded,
-- and every consumer already treats a missing name as a fall-through.

alter table public.maps_geocode_cache
    add column if not exists neighborhood text;
