-- Fanout content scheduler: support a second content type (Local SEO pages)
-- alongside blog posts. The schedule carries the content type and, for local
-- SEO, the target area (a free-text location + optional DataForSEO city code,
-- independent of the session's country-level location_code). Additive +
-- backward-compatible: existing schedules default to 'blog_post'.
alter table fanout.content_schedules
  add column if not exists content_type text not null default 'blog_post'
    check (content_type in ('blog_post', 'local_seo_page')),
  add column if not exists location text,
  add column if not exists location_code integer;
