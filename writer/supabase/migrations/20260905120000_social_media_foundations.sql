-- Social Media module — P0 data foundations (docs/modules/social-media-module-prd-v1_0.md §5).
-- Additive + inert: nothing reads these tables until the module's code ships. RLS on,
-- service-role only (the suite model, like autonomy_foundations). No async_jobs job types
-- here — those land with their handlers (the repo pattern: autonomy_run's type was a
-- separate migration from its foundations). Owner scope decisions baked in: IG carousels,
-- Reels + Stories are in v1, so drafts are multi-image + format-aware.

-- One PostPeer "profile" (== dashboard "Social group") per client — the grouping the
-- provider scopes a client's connected accounts to. Mirrors clients.slack_channel_id /
-- everhour_project_id: a single external id per client, set when we create the profile.
alter table clients
  add column if not exists social_profile_id text;

-- A connection to ONE of the client's own real platform accounts. We store only the
-- provider's opaque account id (the tokens live with PostPeer). status is a small state
-- machine (failure-handling spec §1), not a boolean.
create table if not exists social_accounts (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references clients (id) on delete cascade,
  platform           text not null,
  adapter            text not null default 'postpeer',
  adapter_account_id text not null,
  profile_id         text,
  handle             text,
  status             text not null default 'connected'
                       check (status in ('connected','needs_reauth','revoked','error')),
  connected_at       timestamptz,
  last_checked_at    timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (client_id, platform, adapter_account_id)
);
create index if not exists social_accounts_client_idx on social_accounts (client_id);
alter table social_accounts enable row level security;

-- Per-platform social handles for a competitor. A CHILD of client_competitors, because
-- that table's uniqueness indexes are partial (WHERE domain / place_id IS NOT NULL), so a
-- bare handle-only row would escape dedup and mint duplicate competitors.
create table if not exists social_competitor_handles (
  id            uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references client_competitors (id) on delete cascade,
  platform      text not null,
  handle        text not null,
  created_at    timestamptz not null default now(),
  unique (competitor_id, platform, handle)
);
alter table social_competitor_handles enable row level security;

-- Analyze-in-place research output (ADR-0002): dated per (client, competitor, platform).
-- top_performers holds LINKS ONLY — never re-hosted media.
create table if not exists social_competitor_signals (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients (id) on delete cascade,
  competitor_id  uuid references client_competitors (id) on delete set null,
  platform       text not null,
  themes         jsonb,
  formats        jsonb,
  hook_patterns  jsonb,
  cadence        jsonb,
  top_performers jsonb,
  whats_working  text,
  status         text not null default 'ok'
                   check (status in ('ok','insufficient_data')),
  captured_at    timestamptz not null default now(),
  created_at     timestamptz not null default now()
);
create index if not exists social_competitor_signals_lookup_idx
  on social_competitor_signals (client_id, competitor_id, platform, captured_at desc);
alter table social_competitor_signals enable row level security;

-- A per-platform Draft. Copy is tailored per platform; image_urls is an ARRAY (carousels
-- ship up to 10). source_version stamps the Source at generation time so a later edit is
-- caught (failure spec §3). voice_verdict / spec_verdict are the enforced gates.
create table if not exists social_drafts (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid not null references clients (id) on delete cascade,
  angle_set_id      uuid,
  source_ref        jsonb,
  source_version    text,
  angle             text,
  platform          text not null,
  format            text not null default 'feed'
                      check (format in ('feed','carousel','reel','story','pin','thread','storyboard')),
  copy              text,
  image_urls        text[] not null default '{}',
  platform_metadata jsonb,
  voice_verdict     jsonb,
  spec_verdict      jsonb,
  -- status evolves with the Creator pipeline; left free text on purpose (draft /
  -- generating / needs_image / generation_failed / ready / approved / archived /
  -- source_changed) so P2 can refine it without a constraint migration.
  status            text not null default 'draft',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists social_drafts_client_idx on social_drafts (client_id, created_at desc);
create index if not exists social_drafts_angle_set_idx on social_drafts (angle_set_id);
alter table social_drafts enable row level security;

-- An approved/scheduled/published Post + its lifecycle (GBP-Posts template). status covers
-- the happy path plus the failure/edge holds (failure spec §7).
create table if not exists social_posts (
  id               uuid primary key default gen_random_uuid(),
  draft_id         uuid references social_drafts (id) on delete set null,
  client_id        uuid not null references clients (id) on delete cascade,
  platform         text not null,
  account_id       text,
  scheduled_at     timestamptz,
  published_at     timestamptz,
  provider_post_id text,
  post_url         text,
  status           text not null default 'scheduled'
                     check (status in ('scheduled','publishing','published','blocked_account',
                                       'source_changed','needs_image','generation_failed',
                                       'expired','rejected','failed','cancelled')),
  status_detail    text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists social_posts_client_idx on social_posts (client_id, scheduled_at);
create index if not exists social_posts_status_idx on social_posts (status);
alter table social_posts enable row level security;

-- Per-client tuning (PRD §10): the object humans edit to steer the agents. autonomy_tier
-- is social-scoped (distinct from clients.autonomy_tier, the SEO executor's). monthly
-- ceiling is the fail-closed backstop (§11), defaulting from config at read time when null.
create table if not exists social_policy (
  client_id            uuid primary key references clients (id) on delete cascade,
  cadence              jsonb not null default '{}'::jsonb,
  allowed_topics       jsonb,
  blocked_topics       jsonb,
  tone_prefs           jsonb,
  competitor_focus     jsonb,
  monthly_ceiling_usd  numeric,
  autonomy_tier        smallint not null default 0,
  image_prompt_template text,
  text_prompt_template  text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
alter table social_policy enable row level security;

-- Per-platform constraint data (PRD §6): consumed by BOTH the generation prompt and a
-- deterministic validator. Seeded from the confirmed PostPeer/platform specs; editable.
create table if not exists social_platform_specs (
  platform             text primary key,
  char_limit           integer,
  max_images           integer,
  image_aspect_ratios  jsonb,
  requires_image       boolean not null default false,
  link_policy          text,
  hashtag_norm         jsonb,
  notes                text,
  updated_at           timestamptz not null default now()
);
alter table social_platform_specs enable row level security;

insert into social_platform_specs (platform, char_limit, max_images, image_aspect_ratios, requires_image, link_policy, notes)
values
  ('twitter',   280,  4,  '["16:9","1:1"]'::jsonb,               false, 'link_taxed',
     'X: 280 chars; <=4 images/1 video; a URL in the body costs 50 credits vs 5 (avoid-links-on-X toggle).'),
  ('facebook',  63206, 10, '["1.91:1","1:1","4:5"]'::jsonb,      false, 'allowed',
     'Facebook Pages; photo carousels + link previews supported.'),
  ('instagram', 2200, 10, '["4:5","1:1","1.91:1"]'::jsonb,       true,  'no_link_in_caption',
     'IG: NO text-only posts (>=1 media). Feed 4:5..1.91:1; carousel <=10, one ratio; reel 9:16; story 9:16 Business-only, caption-less.'),
  ('pinterest', 500,  1,  '["2:3","1:1"]'::jsonb,                true,  'allowed',
     'Pinterest pins require an image; board selection in platform_metadata.'),
  ('youtube',   5000, 1,  '["16:9","9:16"]'::jsonb,              false, 'allowed',
     'v1 analyze-only: storyboard/brief + thumbnail + title/description; no video generation.')
on conflict (platform) do nothing;

-- The fail-closed budget meter. Per-client, per-month DOLLAR spend, keyed (client_id,
-- month=first-of-month UTC) — mirrors autonomy_spend exactly (PRD §11 "per-client monthly
-- hard ceiling", which supersedes the §3 "(day, calls)" sketch; consistency with the
-- autonomy governor beats matching a placeholder name). Every paid external call (Apify /
-- TwelveLabs / nano-banana Pro / posting provider) reserves its estimated cost first.
create table if not exists social_usage (
  client_id uuid not null references clients (id) on delete cascade,
  month     date not null,
  spent_usd numeric not null default 0,
  primary key (client_id, month)
);
alter table social_usage enable row level security;

-- Atomic check-and-increment against the client's monthly ceiling. Returns true only when
-- the charge fit (row updated); a refused reservation leaves spend unchanged, so the caller
-- must NOT proceed with the paid action. Mirrors reserve_autonomy_spend (fail-closed).
create or replace function reserve_social_spend(
  p_client uuid, p_month date, p_amount numeric, p_cap numeric
)
returns boolean
language plpgsql
as $$
begin
  insert into social_usage (client_id, month, spent_usd)
    values (p_client, p_month, 0)
    on conflict (client_id, month) do nothing;
  update social_usage
     set spent_usd = spent_usd + p_amount
   where client_id = p_client
     and month = p_month
     and spent_usd + p_amount <= p_cap;
  return found;
end;
$$;
