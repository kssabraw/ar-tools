-- Media pipeline (Phase 1): per-client persistent visual profile + resilient
-- hero fallback, and per-asset media tracking with job states.

-- The persistent client visual profile (generated once from the brand
-- personality, reused for every article so posts stay visually consistent).
alter table clients add column if not exists blog_visual_profile jsonb;

-- Option B (resilient hero): a client-level fallback hero image used when
-- generation fails, so an unattended publish is never blocked.
alter table clients add column if not exists blog_hero_fallback_url text;

-- One row per planned media asset (hero + inline images/charts). Carries the
-- plan, placement, generation state, and the committed reference. Supersedes the
-- thin `run_images` table for the new pipeline.
create table if not exists blog_media_assets (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  asset_id      text not null,                 -- 'hero' | 'inline-1' | 'inline-2'
  role          text not null check (role in ('hero', 'inline')),
  asset_type    text not null default 'image' check (asset_type in ('image', 'chart')),
  status        text not null default 'planned'
                check (status in ('planned', 'validating', 'generating', 'generated',
                                  'uploading', 'uploaded', 'inserted', 'failed', 'skipped')),
  -- Placement (inline only): anchor_type/anchor_id/position/section_id/
  -- fallback_excerpt/fallback_excerpt_occurrence/placement_explanation.
  placement     jsonb,
  concept       text,
  prompt        text,
  alt_text      text,
  caption       text,
  filename      text,
  repo_path     text,        -- committed path in the client repo
  preview_url   text,        -- public bucket URL (review UI)
  width         int,
  height        int,
  model         text,        -- generation model + settings provenance
  confidence    numeric,
  plan          jsonb,       -- the raw asset object from the accepted plan
  used_fallback boolean not null default false,
  error         text,
  skip_reason   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (run_id, asset_id)
);

create index if not exists blog_media_assets_run_id_idx on blog_media_assets (run_id);

alter table blog_media_assets enable row level security;
