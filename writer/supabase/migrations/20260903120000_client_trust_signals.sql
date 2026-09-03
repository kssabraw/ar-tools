-- Client trust signals + media assets (docs/modules/local-landing-page-structure.md
-- — the "Trust & Proof" deterministic block + the expanded Content Gaps list).
--
-- The Local SEO writer injects a deterministic Trust & Proof block (sibling to
-- Contact & Find-Us) whose contents are business-supplied assets or objectively
-- true/false facts — badges, the GBP aggregate rating, financing logos, media —
-- so they can never be hallucinated. Those inputs live here:
--   • clients.trust_signals — the scalar/list facts (certifications, affiliations,
--     financing partners, license number, founding year). One JSONB, mirroring
--     how gbp / differentiators / brand_voice are stored.
--   • client_assets — the media gallery (team/owner photo, branded vehicle,
--     before/after, video embed): genuinely 1-to-many binary uploads, on the
--     public client-logos bucket pattern, so a row per asset.

alter table clients
  add column if not exists trust_signals jsonb;

comment on column clients.trust_signals is
  'Trust & Proof facts for the Local SEO writer (docs/modules/local-landing-page-structure.md): {certifications:[{name,logo_url}], affiliations:[{name,logo_url}], financing_partners:[{name,logo_url}], license_number:text, years_founded:int, founding_date:text}. Rendered deterministically; never model-authored. Null when unset.';

create table if not exists client_assets (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid not null references clients(id) on delete cascade,
  -- The media-gallery slot this asset fills. 'video_embed' stores an embeddable
  -- URL rather than an uploaded file; the rest are image URLs in the public
  -- client-logos bucket.
  kind        text not null
    check (kind in ('team_photo','owner_photo','vehicle','before_after','video_embed','other')),
  url         text not null,
  caption     text,
  sort_order  int not null default 0,
  created_at  timestamptz not null default now(),
  created_by  uuid references profiles(id)
);

create index if not exists client_assets_client_idx
  on client_assets (client_id, sort_order, created_at);

alter table client_assets enable row level security;

create policy "authenticated users read client_assets"
  on client_assets for select
  using (auth.role() = 'authenticated');

comment on table client_assets is
  'Media gallery assets for a client''s Trust & Proof block (team/owner photo, branded vehicle, before/after, video embed). One row per asset; images live in the public client-logos bucket. Rendered deterministically by the Local SEO writer.';
