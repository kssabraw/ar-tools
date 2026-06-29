-- Migration: 20260629170000_asana_task_library.sql
-- Purpose: Asana monthly automation — a global Task Library: the single source
--          of truth for "how long each standard task takes" (+ a default
--          category). Keyed by task NAME. A client template row inherits the
--          library's default hours / category when its own value is blank, so
--          you define "GBP Blast = 1.5h, GBP Authority" once and every client's
--          "GBP Blast" task uses it (override per client by filling the row in).
--          No change to the template table — inheritance is by name match.
--
-- RLS on, NO client-facing policies (service-role only) — the suite convention.

create table if not exists asana_task_library (
  id                    uuid primary key default gen_random_uuid(),
  name                  text not null,
  default_hours         numeric,
  default_category_name text,
  active                boolean not null default true,
  sort_order            integer not null default 0,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

-- Name is the key (case-insensitive); a template row inherits by matching it.
create unique index if not exists idx_asana_task_library_name
  on asana_task_library (lower(name));

alter table asana_task_library enable row level security;
