-- Soft-delete for Local SEO pages.
--
-- Deleting a page from "Saved Pages" now moves it to a "Drafts" bin (sets
-- deleted_at) instead of removing it, so it can be restored or permanently
-- deleted from the Drafts tab. A NULL deleted_at = active (Saved Pages); a
-- non-NULL deleted_at = drafted/trashed (Drafts tab).

alter table local_seo_pages
  add column if not exists deleted_at timestamptz;

-- List queries filter on (client_id, deleted_at) for both tabs.
create index if not exists idx_local_seo_pages_client_deleted
  on local_seo_pages (client_id, deleted_at);
