-- ============================================================
-- Fanout content scheduler: allow service pages as a third content type
-- ============================================================
-- Extends fanout.content_schedules.content_type to include 'service_page'
-- (alongside 'blog_post' and 'local_seo_page'). A service_page schedule
-- creates a suite service_page run (service_brief -> service_writer) per
-- cluster keyword — keyword-only, against the session's linked client.
-- Additive + backward-compatible.
-- ============================================================

alter table fanout.content_schedules
  drop constraint if exists content_schedules_content_type_check;

alter table fanout.content_schedules
  add constraint content_schedules_content_type_check
    check (content_type in ('blog_post', 'local_seo_page', 'service_page'));
