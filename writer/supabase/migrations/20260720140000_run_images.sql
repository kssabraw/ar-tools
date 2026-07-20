-- Generated blog-post images (hero + body illustrations/charts) as first-class,
-- per-run assets. Populated by the blog_github_publish flow: OpenAI gpt-image-1
-- renders each planned slot, the bytes are committed into the client's repo
-- (public/images/blog/<slug>/...) and previewed from the public content bucket.
--
-- One row per image. `role` splits the hero from body images; `kind` splits a
-- plain illustration from a chart (the planner decides, the prompt differs).
-- `position` orders body images; `anchor_heading` is the section heading the
-- image is placed after (robust to re-ordering). `repo_path` is the committed
-- path the markdown references; `preview_url` is the public bucket URL the
-- review UI shows.
create table if not exists run_images (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  role          text not null check (role in ('hero', 'body')),
  kind          text not null default 'illustration' check (kind in ('illustration', 'chart')),
  position      int  not null default 0,
  anchor_heading text,
  alt           text,
  prompt        text,
  preview_url   text,
  repo_path     text,
  status        text not null default 'pending'
                check (status in ('pending', 'generating', 'ready', 'committed', 'failed')),
  error         text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists run_images_run_id_idx on run_images (run_id);

-- Service-role only (the backend uses the service key; no client-side reads).
alter table run_images enable row level security;
