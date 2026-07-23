-- Migration: 20260723110000_gbp_oauth.sql
-- Purpose: store the agency GBP OAuth refresh token captured by the in-app
--   "Connect Google Business Profile" flow (routers/gbp_oauth.py), so posting
--   authenticates as the agency Google account that manages the client listings
--   — the SaaS "Sign in with Google" model, no CLI token-grab and no per-client
--   OAuth. Agency-level: ONE row (provider = 'gbp'). services/gbp_auth reads the
--   refresh token from here (falling back to the GBP_OAUTH_REFRESH_TOKEN env).
--
-- RLS enabled, no policies — written/read only by the service-role backend
-- (the token is a credential; never exposed to the anon/client key).

create table if not exists gbp_oauth_credentials (
  provider       text primary key default 'gbp',
  refresh_token  text not null,
  account_email  text,
  connected_by   uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

alter table gbp_oauth_credentials enable row level security;
