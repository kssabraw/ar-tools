-- Intake-card fields: human-curated targeted services + freeform client notes.
-- Both live on the client row, captured under "Search Console & Local Rankings".
--   * targeted_services — the services the client wants to target/rank for.
--     Structured (text[]) so it can feed the Local SEO planner (matrix services
--     axis) and the agents (SerMaStr / strategist context). Mirrors target_cities.
--   * client_notes — freeform internal notes. AI-readable (surfaced to the
--     SerMaStr + strategist client-context providers).
alter table public.clients
  add column if not exists targeted_services text[] not null default '{}'::text[],
  add column if not exists client_notes text;

comment on column public.clients.targeted_services is
  'Human-curated services the client wants to target/rank for. Feeds agent context (SerMaStr/strategist) and the Local SEO matrix planner. Comma-separated on the intake card.';
comment on column public.clients.client_notes is
  'Freeform internal notes captured on the intake card. AI-readable (SerMaStr/strategist client context).';
