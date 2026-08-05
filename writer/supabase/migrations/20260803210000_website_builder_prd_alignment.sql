-- Website Builder — align the schema with the PRD and the Page Type Reference.
--
-- The first migration was written against the plan's pre-ruling assumptions.
-- The PRD (docs/modules/website-builder-prd-v1_0.md) and the Page Type
-- Reference v3.4 (docs/reference/page-type-reference-v3_4.md) settled four
-- things the original tables actively prevent. Each is fixed here.

-- 1. lead_gen is a third site type, not a variant of local_business (PRD §4.12).
--    It shares the geo silo and the service × city matrix but differs on
--    identity, schema, facts and metrics.
alter table websites drop constraint if exists websites_site_type_check;
alter table websites
  add constraint websites_site_type_check
  check (site_type in ('local_business', 'informational', 'lead_gen'));

-- 2. Lifecycle states (PRD §3.1). Unpublish and delete are different acts and
--    neither is a purge: delete removes the row from our lists and leaves the
--    site serving, because the repo IS the site.
alter table websites add column if not exists unpublished_at timestamptz;
alter table websites add column if not exists deleted_at timestamptz;

-- 3. monetization is orthogonal to site_type (PRD §4.15.4) — a client's local
--    site is 'leads'; an owned property may be leads, or ads + affiliate, or
--    both. Reading it off the site type would be right most of the time and
--    wrong exactly where it matters. Empty array = an authority site with no
--    ad config, no affiliate table and no disclosure surface.
alter table websites add column if not exists monetization text[] not null default '{}';
alter table websites
  add constraint websites_monetization_values
  check (monetization <@ array['ads', 'affiliate', 'leads']::text[]);

-- 4. theme_source records what PRODUCED a theme (PRD §4.14), which is not the
--    same question as source_kind's "what kind of file came in". v1 supports
--    only design_import, but the column exists from the start so the generated
--    escape hatch does not mean touching every theme row later. Nothing
--    downstream of theme approval may branch on this.
alter table website_themes add column if not exists theme_source text not null default 'design_import';
alter table website_themes
  add constraint website_themes_theme_source_check
  check (theme_source in ('design_import', 'generated', 'house'));

-- 5. Published slugs are immutable; a rename keeps the old path as a 301
--    (reference §1.2, PRD §4.8). The original unique(website_id, route) made
--    that impossible — the redirect source and its replacement both need rows.
--    The guarantee worth keeping is narrower: two *live* pages may not claim
--    one path, which the reference calls a planning error.
alter table website_pages add column if not exists page_type text;
alter table website_pages add column if not exists superseded_at timestamptz;
alter table website_pages add column if not exists redirect_to text;

alter table website_pages drop constraint if exists website_pages_website_id_route_key;

create unique index if not exists website_pages_active_route_idx
  on website_pages (website_id, route)
  where superseded_at is null;

-- Superseded rows are read as a set to build the repo's _redirects artifact,
-- so they are queried by site + supersession, not by route.
create index if not exists website_pages_superseded_idx
  on website_pages (website_id)
  where superseded_at is not null;

-- 6. An owned lead-gen or informational property still lives on a client row
--    (locked ruling — every site belongs to a client), but it is not a client.
--    `kind` lets client-scoped surfaces, reporting and LeadOff dup checks
--    filter properties out without a second table. Existing rows are clients.
alter table clients add column if not exists kind text not null default 'client';
alter table clients
  add constraint clients_kind_check
  check (kind in ('client', 'owned_property'));

create index if not exists clients_kind_idx on clients(kind) where kind <> 'client';
