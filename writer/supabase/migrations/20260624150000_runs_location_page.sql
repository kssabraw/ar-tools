-- ============================================================
-- runs: add the location_page content type + services column
-- ============================================================
-- A location page is a multi-service hub for ONE location (typically right off
-- the domain root, e.g. /austin) that covers each major service the client
-- offers in that area. It runs through the SAME two-stage path as a service
-- page (service_brief -> service_writer) and the same auto-score/reoptimize
-- stages, so no new statuses are needed — it reuses the service_* statuses
-- (phase-descriptive). It differs only in: the brief/writer run in 'location'
-- page_type (section-per-service), scoring runs in LOCAL geo_mode (geo engines
-- count), and the run carries the list of services to cover.
--
-- `services` is the major services the location page must cover (one section
-- each). Empty for every other content type. Additive; existing rows + the
-- blog/service pipelines are unaffected.
-- ============================================================

alter table runs add column if not exists services jsonb not null default '[]'::jsonb;

alter table runs drop constraint if exists runs_content_type_check;
alter table runs add constraint runs_content_type_check
  check (content_type in ('blog_post', 'service_page', 'location_page'));
