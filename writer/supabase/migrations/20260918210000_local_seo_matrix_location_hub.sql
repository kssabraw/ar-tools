-- Local SEO matrix: "up" link to the location hub page.
--
-- Besides linking up to its top-level service page (`link_to_service_hub`) and
-- the site root (`link_to_home`), each generated page can also link UP to its
-- top-level (service-agnostic) LOCATION page — e.g. /melbourne/ — completing the
-- silo spine (this-service-everywhere ↑, this-location-everything ↑, home ↑).
--
-- Not every client site has per-location hub pages, so this defaults OFF (unlike
-- the near-universal service hub). `location_hub_pattern` carries a single
-- {location} token (e.g. /{location}/ or /areas-we-serve/{location}/).

alter table public.local_seo_matrices
  add column if not exists link_to_location_hub boolean not null default false,
  add column if not exists location_hub_pattern  text    not null default '/{location}/';
