-- Persist a run's Google Docs publish target so the UI can show an
-- "already published" badge (and a link to the Doc) instead of re-publishing
-- blindly. Mirrors local_seo_pages' published_* columns. Additive +
-- backward-compatible: existing runs are null (never published from the app).
alter table public.runs
  add column if not exists published_doc_id text,
  add column if not exists published_doc_url text,
  add column if not exists published_at timestamptz;
