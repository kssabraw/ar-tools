-- Per-run "mirror an existing page's structure" URL for service / location page
-- creation. When set, the service-page orchestrator scrapes this page's section
-- layout and mirrors it for THIS run only, overriding the client's saved
-- reference structure (clients.page_structures[service|location]). Blank ⇒ the
-- client's saved reference (or the default structure) is used, as before.
alter table runs add column if not exists reference_page_url text;
