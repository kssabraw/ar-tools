-- Keyword Research report (Topic Fan-out): a generated PDF deliverable
-- summarizing a session's keyword research — topic silos, search demand, top
-- opportunities, and the content plan — saved to the client's Drive folder and
-- downloadable in-app. One row per generated report (history + re-download),
-- mirroring fanout.csv_exports.
create table if not exists fanout.keyword_reports (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references fanout.sessions(id) on delete cascade,
    created_by      uuid,
    title           text not null,
    storage_path    text,                 -- private `reports` bucket object key (download)
    drive_url       text,                 -- Google Doc/PDF URL in the client's Drive (null if not client-linked)
    status          text not null default 'complete',  -- complete | failed
    error           text,
    generated_at    timestamptz not null default now()
);

create index if not exists keyword_reports_session_idx
    on fanout.keyword_reports (session_id, generated_at desc);

-- Backend-only table: accessed exclusively via the service-role client (after a
-- session-visibility check in the API), so enable RLS with no policies to deny
-- all anon/authenticated PostgREST access (the fanout schema is exposed).
alter table fanout.keyword_reports enable row level security;
