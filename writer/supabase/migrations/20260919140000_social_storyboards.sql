-- Social Media P5 (slice a) — Video Storyboard deliverables.
--
-- A storyboard is a PLANNING deliverable (a shot-by-shot brief the client shoots),
-- NOT a publishable post — so it gets its own table rather than overloading
-- social_drafts (which is a copy+media row bound to the publish lifecycle). No video
-- is generated or assembled: this slice produces the brief only (owner Q1 = a).
-- One row per generated storyboard. Service-role only (like every social table).

create table if not exists social_storyboards (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  platform       text not null,                         -- instagram | facebook | youtube
  format         text not null default 'reel',          -- reel | short
  source_type    text,                                  -- topic | url | blog_run | local_seo_page
  source_ref     jsonb,                                 -- {type, url|run_id|page_id}
  source_title   text,
  source_version text,                                  -- creator.source_version_of (edited-source guard)
  angle          text,
  tone           text,
  title          text,                                  -- working title
  storyboard     jsonb not null default '{}'::jsonb,    -- {hook, duration_seconds, shots[], music, caption, hashtags[], cta}
  thumbnail_url  text,
  voice_warnings jsonb,                                 -- forbidden-term advisories (best-effort, not auto-corrected)
  status         text not null default 'generated',     -- generated | archived
  created_by     uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint social_storyboards_status_chk check (status in ('generated', 'archived'))
);

alter table social_storyboards enable row level security;

-- The list view reads a client's live storyboards, newest first.
create index if not exists social_storyboards_client_idx
  on social_storyboards (client_id, created_at desc)
  where status <> 'archived';
