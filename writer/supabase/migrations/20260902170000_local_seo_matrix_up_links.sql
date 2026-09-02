-- Local SEO matrix: "up" internal links.
--
-- Besides interlinking siblings, each generated location page can also link UP
-- the site hierarchy: to its top-level (location-agnostic) service page and to
-- the site root. Both default on. `service_hub_pattern` carries a single
-- {service} token (e.g. /{service}/ or /services/{service}/).

alter table public.local_seo_matrices
  add column if not exists link_to_service_hub boolean not null default true,
  add column if not exists service_hub_pattern  text    not null default '/{service}/',
  add column if not exists link_to_home         boolean not null default true;
