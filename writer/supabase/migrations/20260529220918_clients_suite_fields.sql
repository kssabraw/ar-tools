-- Add suite-level fields to clients (AR Tools multi-module suite):
--   logo_url          → client-tile branding on the suite dashboard
--   gsc_property      → Google Search Console property for service-account
--                       metrics ingestion (e.g. "sc-domain:acmehvac.com" or
--                       "https://acmehvac.com/")
--   business_location → primary business location used to anchor the
--                       maps / local-pack rank-tracking geo-grid
alter table clients add column if not exists logo_url text;
alter table clients add column if not exists gsc_property text;
alter table clients add column if not exists business_location text;
