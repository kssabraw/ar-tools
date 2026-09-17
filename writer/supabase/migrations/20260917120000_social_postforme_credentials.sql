-- Social Media module — PostForMe per-client project API keys (ADR-0001 provider swap).
--
-- PostForMe replaces PostPeer as the posting provider. Unlike PostPeer's one
-- account-wide key, a PostForMe API key is scoped to a single Project, and there is
-- one Project per client — so the key IS the client-isolation boundary (a client's
-- key cannot see or post to another client's accounts; verified empirically). We
-- therefore store a per-client project key.
--
-- It's a SECRET, so it must NOT live on `clients` (which is `select("*")`-ed into
-- frontend responses). It goes in this dedicated, RLS/service-role-only table, mirroring
-- how the suite stores other provider secrets (e.g. gbp_oauth_credentials.refresh_token
-- is a plaintext text column in a service-role-only table). Never returned to the
-- frontend — the UI only ever sees a {configured: bool} status.
--
-- Provisioning is MANUAL: PostForMe exposes no project/key-management API, so an admin
-- creates the client's Project in the PostForMe dashboard, generates its key, and pastes
-- it here (validated via a live check_auth before it's stored). Additive + inert until
-- SOCIAL_POSTING_PROVIDER=postforme is set on PLATFORM. No async_jobs job types here.
create table if not exists social_client_credentials (
  client_id   uuid primary key references clients (id) on delete cascade,
  provider    text not null default 'postforme',
  api_key     text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
alter table social_client_credentials enable row level security;
