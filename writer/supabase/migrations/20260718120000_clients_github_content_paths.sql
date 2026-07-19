-- Per-content-type GitHub repo content paths for publishing (enhancement #1).
-- A JSONB map keyed by content_type slug → repo content path, e.g.
--   {"blog_post": "src/content/blog", "service_page": "src/content/services",
--    "location_page": "src/content/locations"}
-- github_content_path remains the single default/fallback used when a content
-- type has no entry here; the server-side github_default_content_path is the
-- final fallback. Mirrors the drive_folders / google_drive_folder_id pattern.
alter table public.clients
  add column if not exists github_content_paths jsonb not null default '{}'::jsonb;
