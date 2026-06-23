-- Link Topic Fanout runs to an AR Tools client (client-scoped runs) and scaffold
-- per-client publish targets read from the client dashboard.
-- Applied to prod via Supabase MCP on 2026-06-23.

-- A Fanout run (session) can belong to a client. Nullable so the global/owner
-- view still works for client-less runs; SET NULL so deleting a client keeps its
-- runs (detached) rather than cascading them away.
alter table fanout.sessions
  add column if not exists client_id uuid
  references public.clients(id) on delete set null;

create index if not exists idx_fanout_sessions_client_id
  on fanout.sessions(client_id);

-- Publish-target scaffold (#3): the Drive folder already lives on
-- public.clients.google_drive_folder_id; add the GitHub repo target so the
-- Fanout publish path can later resolve both from the client dashboard.
alter table public.clients
  add column if not exists github_repo text,
  add column if not exists github_branch text,
  add column if not exists github_content_path text;
