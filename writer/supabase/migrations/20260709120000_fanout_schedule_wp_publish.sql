-- Fanout content schedules: optional direct-to-WordPress publishing.
-- wp_publish opts a schedule's finished blog posts into the client's WordPress
-- site (alongside the existing auto_publish Drive copy); wp_status picks
-- whether they land as drafts or go live immediately.
alter table fanout.content_schedules
  add column if not exists wp_publish boolean not null default false,
  add column if not exists wp_status text not null default 'draft'
    check (wp_status in ('draft', 'publish'));
