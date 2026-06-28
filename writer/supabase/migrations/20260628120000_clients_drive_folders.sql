-- Per-content-type Google Drive folders for publishing.
-- A JSONB map keyed by content_type slug → Drive folder ID, e.g.
--   {"blog_post": "1A..", "service_page": "1B..", "location_page": "1C..",
--    "local_seo_page": "1D..", "ecom_page": "1E..", "use_case": "1F.."}
-- google_drive_folder_id remains the default/fallback used when a content type
-- has no entry here (ecom_page / use_case are reserved for future modules).
alter table clients
  add column if not exists drive_folders jsonb not null default '{}'::jsonb;
