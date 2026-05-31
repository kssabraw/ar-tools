-- Add Google Business Profile (GBP) data to clients.
--
-- Stored as a JSONB blob plus a dedicated place_id column, mirroring the
-- local-seo-writer `business_profiles` shape so the two can interoperate:
--   gbp_place_id  → business_profiles.gbp_place_id
--   gbp (jsonb)   → {
--       business_name, description, address, phone, website, logo, photo,
--       gbp_category, gbp_categories[], gbp_rating, gbp_review_count,
--       latitude, longitude, hours, google_maps_uri
--   }
--
-- Populated manually for now; an Outscraper/Google auto-fetch can fill the
-- same shape later without a schema change.
ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS gbp_place_id text,
  ADD COLUMN IF NOT EXISTS gbp jsonb;
