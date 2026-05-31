-- Dedicated PUBLIC storage bucket for client logos.
--
-- Public so the dashboard tile + client-workspace header can render the
-- image directly via <img src> — the value stored in clients.logo_url is
-- this bucket's public object URL. Restricted to JPG/PNG with a 2 MB cap.
--
-- Writes happen from platform-api using the service-role key (bypasses
-- RLS); reads are served publicly via the public object URL, so no extra
-- storage.objects policies are required.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'client-logos',
  'client-logos',
  true,
  2097152,                              -- 2 MB
  array['image/jpeg', 'image/png']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
