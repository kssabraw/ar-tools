-- Migration: 20260629230000_sops.sql
-- Purpose: SOP / playbook store. Holds the agency's standard operating procedures
--          and strategic "theories" so the reoptimization planner can ground its
--          per-action recommendations in the agency's own methodology (and voice).
--
--          Two layers (per the chosen design):
--            - agency-wide  → client_id IS NULL  (applies to every client)
--            - per-client   → client_id set      (overrides / augments for one client)
--
--          Content is parsed plain text (pasted directly, or extracted from an
--          uploaded doc via /files/upload before insert). The planner's enrichment
--          step reads enabled rows for a client + the agency-wide rows.
--
-- RLS on, NO client-facing policies (service-role only — the frontend reads/writes
-- exclusively through the platform API, like every other suite table).

create table if not exists sops (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid references clients(id) on delete cascade,   -- NULL = agency-wide
  title       text not null,
  content     text not null,                                   -- parsed plain text
  category    text not null default 'general'
                check (category in (
                  'general', 'reoptimization', 'link_building',
                  'local', 'content', 'theory'
                )),
  source      text not null default 'paste'                    -- paste | upload
                check (source in ('paste', 'upload')),
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Agency-wide rows (client_id IS NULL) and per-client rows are both queried by the
-- enrichment step; index covers both the global and the scoped read.
create index if not exists idx_sops_client on sops (client_id, enabled);
create index if not exists idx_sops_agency on sops (enabled) where client_id is null;

alter table sops enable row level security;
