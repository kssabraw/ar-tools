-- Manual target-city list for the Local SEO silo planner's target-city discovery.
-- One of the sources (alongside the GBP service area, the client's own site, and a
-- ~10-mile Overpass radius sweep) for the cities the planner builds location pages
-- for beyond the seed city. Additive + safe: defaults to an empty array.
alter table public.clients
  add column if not exists target_cities text[] not null default '{}';
