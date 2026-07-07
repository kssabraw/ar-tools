-- Saved geo-grid map images (Maps Module #5).
--
-- A rendered PNG of each per-keyword scan result — Google's static-map tile with
-- the numbered rank pins composited on top (services/maps_image.py). Persisted so
-- the exact map the team sees can be archived and embedded in reports.
--
-- PUBLIC bucket so the stored URL renders directly via <img src> (client
-- workspace), embeds in the WeasyPrint client PDF, and is fetchable by the Apps
-- Script webhook when it inserts the image into the Maps Google Doc. Writes come
-- from platform-api with the service-role key (bypasses RLS); reads are public.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'maps-images',
  'maps-images',
  true,
  5242880,                              -- 5 MB
  array['image/png']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Public URL of the rendered map PNG for this (scan, keyword) result. Distinct
-- from the (dead) heatmap_image_url, which held Local Dominator's own external
-- image link and is unused by the app.
alter table maps_scan_results add column if not exists map_image_url text;
