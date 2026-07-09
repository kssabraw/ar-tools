-- Fanout: user-specified extra internal-link targets.
--
-- Up to 3 URLs (money pages — product/service/landing pages) the user wants
-- every generated article in the session to link to. Folded into the M15
-- internal-link injection alongside the architecture graph's targets, under
-- the ≤5-outbound-links-per-page owner rule. Set via the schedule-create
-- endpoint (like site_base_url).
alter table fanout.sessions
  add column if not exists extra_link_urls jsonb not null default '[]'::jsonb;
