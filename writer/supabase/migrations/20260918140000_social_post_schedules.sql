-- Social Media P3 (Manager) — the cadence / recurrence engine.
--
-- One schedule row per (client, platform): a DST-correct recurring cadence
-- (weekly / biweekly / monthly) whose per-tick sweep (enqueue_due_social_schedules)
-- either DRIPS an explicitly-queued approved draft (auto_fill, gated) or emits a
-- suggest-nudge notification. Clones the gbp_post_schedules pattern; cadence config
-- lives here (social_policy.cadence stays inert). Service-role only.

create table if not exists social_post_schedules (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references clients (id) on delete cascade,
  platform      text not null,                 -- one row per (client, platform)
  account_id    text,                          -- the connected account auto_fill drips to
  cadence       text not null default 'disabled',   -- disabled | weekly | biweekly | monthly
  day_of_week   smallint,                      -- 0=Mon (weekly / biweekly)
  day_of_month  smallint,                      -- 1..28 (monthly)
  hour_local    smallint not null default 9,   -- client-local hour (DST-correct)
  is_active     boolean not null default false,
  auto_fill     boolean not null default false,   -- opt-in: drip queued drafts unattended
  next_run_at   timestamptz,
  last_run_at   timestamptz,
  created_by    uuid,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint social_post_schedules_client_platform_uniq unique (client_id, platform),
  constraint social_post_schedules_cadence_chk
    check (cadence in ('disabled', 'weekly', 'biweekly', 'monthly'))
);

alter table social_post_schedules enable row level security;

-- The per-tick sweep queries active, due, non-disabled schedules.
create index if not exists social_post_schedules_due_idx
  on social_post_schedules (next_run_at)
  where is_active and cadence <> 'disabled';
