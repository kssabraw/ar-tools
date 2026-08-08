-- Signed-URL delivery for the client-facing report PDF (report increment 4, the optional refinement).
--
-- reporting-layer-spec §5: a prospect audit is delivered as a SIGNED URL, no auth, ~90-day expiry —
-- so a client gets a link instead of the agency downloading and emailing the file. The spec names
-- Cloudflare R2; this uses a private SUPABASE STORAGE bucket instead (DECISIONS 2026-08-08): the
-- substance the spec asks for is "a signed URL with an expiry", Supabase Storage delivers exactly
-- that, platform-api already holds this project's service-role key (no new R2 credentials to
-- provision — the outreach service carries only Outscraper/DataForSEO/Supabase creds today), and it
-- is reversible to R2 later behind the same `sign_report_url` seam.
--
-- `storage_path` records WHERE the approved bytes live, so a stale signed URL can be re-signed
-- without regenerating (and re-approving) the PDF. The content_hash already on the row names the
-- exact bytes; the path names where they are.

alter table report_approval add column if not exists storage_path text;

comment on column report_approval.storage_path is
  'Object path in the private outreach-reports bucket for the approved PDF, so its signed URL can '
  'be refreshed without re-rendering. Null on approvals recorded before this column (the byte '
  'download still worked).';

-- A private bucket for the rendered PDFs. Service-role only (RLS on storage.objects is bypassed by
-- the service role platform-api holds); signed URLs are how a prospect reads without auth.
insert into storage.buckets (id, name, public)
values ('outreach-reports', 'outreach-reports', false)
on conflict (id) do nothing;
