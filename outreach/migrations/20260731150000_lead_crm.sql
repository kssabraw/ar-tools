-- Migration: 20260731150000_lead_crm.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Phase 1b — the lead CRM layer. Runs in parallel with the scanning
--            pipeline and takes no dependency on it: no scanning, no scoring,
--            no enrichment, no outbound sending.
--
-- Phase boundaries respected here:
--   * `outcome` and `touch` are Phase 3's (written at emit). This migration
--     creates neither and pre-alters neither. It ships the two shapes Phase 3
--     adopts — lead's unique (prospect_id, source), and lead_activity.touch_id
--     without its FK — documented in outreach/PHASE3-outcome-constraint.md.
--   * `suppression` is Phase 1's. Patched additively, never recreated.
--
-- Access model (see ../DECISIONS.md): these tables are read directly by a low-code
-- UI over PostgREST, not through a service that holds the service role. So
-- unlike every other table in the estate they carry real policies. Policies
-- start permissive — any authenticated user sees every lead — because the point
-- is a tested RLS path in place before anything sensitive flows through it.

-- ---------------------------------------------------------------------------
-- Pipeline stages. A lookup table rather than an enum, so the UI renders its
-- dropdown from data and a vocabulary change is an insert rather than a
-- migration. The table is the right shape; THE VALUES ARE WRONG.
--
-- docs/crm-layer-spec.md §3 names lead_stage as new, contacted, replied,
-- in_conversation, won, lost, nurture. These were guessed before that spec was
-- available. 'qualified' is the worst of them: §8a records a deliberate
-- decision to COLLAPSE qualified into in_conversation, precisely so that two
-- incompatible stage vocabularies never coexist in one analysis — which is what
-- reintroducing it produces. 'disqualified' is a lost_reason in the spec, not a
-- stage. Corrected by the reconcile migration (ISSUES.md R-012); left as written
-- so the original mistake stays legible in the history.
-- ---------------------------------------------------------------------------
create table if not exists lead_status (
  key         text primary key,
  label       text not null,
  sort_order  integer not null default 0,
  is_terminal boolean not null default false,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

insert into lead_status (key, label, sort_order, is_terminal) values
  ('new',          'New',          0, false),
  ('contacted',    'Contacted',    1, false),
  ('engaged',      'Engaged',      2, false),
  ('qualified',    'Qualified',    3, false),
  ('won',          'Won',          4, true),
  ('disqualified', 'Disqualified', 5, true),
  ('nurture',      'Nurture',      6, false)
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- lead
--
-- `source` is the spine. The outbound-only rule hangs off it, so it is not
-- null, checked, and half of the unique key Phase 3 will reference.
--
-- 'outbound_scan' is the exact token Phase 3's check constraint will compare
-- against — it must not drift.
--
-- THE OTHER TWO TOKENS ARE WRONG. Built before docs/crm-layer-spec.md was
-- available, this guessed 'inbound' and 'referral'. §3 names a six-value enum:
-- outbound_scan, inbound_form, inbound_call, referral, manual, partner. So this
-- check cannot record a MANUAL lead, which is Phase 1b's primary use case.
-- Corrected by 20260731190000_lead_crm_spec_reconcile.sql (ISSUES.md R-012).
-- Left here as written so the original mistake is legible in the history.
--
-- prospect_id is NULLABLE and does not imply outbound: a promoted inbound lead
-- gets one too. That is exactly why the outbound-only constraint cannot key on
-- prospect alone — see PHASE3-outcome-constraint.md.
-- ---------------------------------------------------------------------------
create table if not exists lead (
  id                  uuid primary key default gen_random_uuid(),

  source              text not null
                        check (source in ('outbound_scan', 'inbound', 'referral')),
  status              text not null default 'new' references lead_status(key),
  owner_id            uuid references auth.users(id) on delete set null,
  prospect_id         uuid references prospect(id) on delete set null,

  business_name       text,
  contact_name        text,
  email               text,
  phone               text,
  website             text,
  city                text,
  state               text,
  postal_code         text,
  country             text,
  category            text,

  intake_channel      text,        -- inbound only: which form/webhook
  intake_payload      jsonb,       -- inbound only: raw body, kept verbatim
  notes               text,

  -- Suppression is recorded, never enforced by refusing the write. Enforcement
  -- at send time is Phase 3's.
  suppressed_at       timestamptz,
  suppression_reason  text,

  deleted_at          timestamptz,
  created_by          uuid references auth.users(id) on delete set null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  email_normalized    text generated always as (lower(nullif(trim(email), ''))) stored,

  -- The FK target Phase 3 adopts. A plain (non-partial) unique constraint,
  -- because Postgres cannot reference a partial unique index from an FK.
  -- Rows with a null prospect_id do not collide: nulls are distinct.
  constraint lead_prospect_source_key unique (prospect_id, source)
);

-- One prospect becomes at most one lead. Combined with the composite key above,
-- this means a prospect resolves to exactly one source — so Phase 3's FK can
-- decide outbound-vs-not without ambiguity.
create unique index if not exists lead_prospect_id_key
  on lead (prospect_id) where prospect_id is not null;

create index if not exists lead_owner_idx    on lead (owner_id);
create index if not exists lead_status_idx   on lead (status);
create index if not exists lead_source_idx   on lead (source);
create index if not exists lead_email_idx    on lead (email_normalized)
  where email_normalized is not null;
create index if not exists lead_live_idx     on lead (created_at desc)
  where deleted_at is null;

-- ---------------------------------------------------------------------------
-- lead_activity — human commentary ONLY.
--
-- `touch` is authoritative for "a contact attempt happened". This table must
-- never also record sends, or the timeline exists twice in two shapes and the
-- two disagree the first time one write path fails. Hence no 'email_sent' and
-- no 'call' kind: a call gets a 'call_note' carrying the touch it comments on.
--
-- touch_id has NO foreign key yet — `touch` is Phase 3's and does not exist.
-- Phase 3 adds the constraint (PHASE3-outcome-constraint.md).
-- ---------------------------------------------------------------------------
create table if not exists lead_activity (
  id          uuid primary key default gen_random_uuid(),
  lead_id     uuid not null references lead(id) on delete cascade,
  occurred_at timestamptz not null default now(),
  actor_id    uuid references auth.users(id) on delete set null,  -- null = system
  kind        text not null
                check (kind in ('note', 'call_note', 'meeting',
                                'status_change', 'assignment', 'suppressed', 'other')),
  touch_id    bigint,
  body        text,
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),

  -- A touch reference is only meaningful on commentary about a touch.
  constraint lead_activity_touch_on_call_note_only
    check (touch_id is null or kind = 'call_note')
);

create index if not exists lead_activity_lead_idx
  on lead_activity (lead_id, occurred_at desc);
create index if not exists lead_activity_touch_idx
  on lead_activity (touch_id) where touch_id is not null;

-- ---------------------------------------------------------------------------
-- suppression — Phase 1's table. Patch, do not recreate.
--
-- `create table if not exists` alone is not enough: when the table exists the
-- whole statement is skipped, so the columns this layer reads would be silently
-- absent. The create is kept for a from-scratch rebuild; the alters below run
-- unconditionally and are what actually apply to the live table.
--
-- Deliberately NO check constraint on `scope`: Phase 1 wrote none and left no
-- rows, so its vocabulary is undocumented, and inventing one here would reject
-- Phase 3's emit-path writes. The intake trigger matches the scopes it knows
-- and ignores any others, which stays correct whatever the real set turns out
-- to be.
-- ---------------------------------------------------------------------------
create table if not exists suppression (
  id         uuid primary key default gen_random_uuid(),
  scope      text not null,
  value      text not null,
  created_at timestamptz not null default now()
);

alter table suppression add column if not exists reason     text;
alter table suppression add column if not exists expires_at timestamptz;   -- null = permanent
alter table suppression add column if not exists created_by uuid references auth.users(id);

-- Safe today because the table holds zero rows. If this ever fails on a rebuild
-- against real data, that is duplicate suppression entries reporting themselves
-- — resolve them by hand rather than deduping automatically.
-- Also the lookup index the intake trigger uses. It cannot be narrowed to live
-- rows only: `now()` is not immutable, so it is illegal in an index predicate.
-- Liveness is filtered at query time instead.
create unique index if not exists suppression_scope_value_key
  on suppression (scope, value);

create index if not exists suppression_value_idx on suppression (value);

-- ---------------------------------------------------------------------------
-- Triggers
-- ---------------------------------------------------------------------------

create or replace function lead_touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists lead_updated_at on lead;
create trigger lead_updated_at before update on lead
  for each row execute function lead_touch_updated_at();

-- Suppression check at intake. Flags, never rejects: dropping an inbound lead
-- because a stale suppression matched is unrecoverable, whereas a flagged row
-- is visible and reversible. Lives in a trigger rather than the intake function
-- so no write path can skip it.
create or replace function lead_flag_suppressed() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  hit        suppression%rowtype;
  candidates text[];
  place      text;
begin
  select p.place_id into place from prospect p where p.id = new.prospect_id;

  candidates := array_remove(array[
    lower(nullif(trim(new.email), '')),
    lower(nullif(split_part(new.email, '@', 2), '')),
    regexp_replace(coalesce(new.phone, ''), '[^0-9]', '', 'g'),
    place
  ], null);
  candidates := array_remove(candidates, '');

  if array_length(candidates, 1) is null then
    return new;
  end if;

  select * into hit from suppression s
   where s.value = any (candidates)
     and (s.expires_at is null or s.expires_at > now())
   limit 1;

  if found then
    new.suppressed_at      := now();
    new.suppression_reason := coalesce(hit.reason, 'matched suppression: ' || hit.scope);
  end if;

  return new;
end;
$$;

drop trigger if exists lead_suppression_check on lead;
create trigger lead_suppression_check before insert on lead
  for each row execute function lead_flag_suppressed();

-- Timeline completeness: status and owner changes are recorded regardless of
-- whether the edit came from Retool, a SQL console, or a later service.
create or replace function lead_log_changes() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status is distinct from old.status then
    insert into lead_activity (lead_id, actor_id, kind, body, metadata)
    values (new.id, auth.uid(), 'status_change',
            format('Status %s → %s', old.status, new.status),
            jsonb_build_object('from', old.status, 'to', new.status));
  end if;

  if new.owner_id is distinct from old.owner_id then
    insert into lead_activity (lead_id, actor_id, kind, body, metadata)
    values (new.id, auth.uid(), 'assignment',
            case when new.owner_id is null then 'Unassigned' else 'Assigned' end,
            jsonb_build_object('from', old.owner_id, 'to', new.owner_id));
  end if;

  return null;
end;
$$;

drop trigger if exists lead_change_log on lead;
create trigger lead_change_log after update on lead
  for each row execute function lead_log_changes();

-- A suppressed lead says so on its own timeline.
create or replace function lead_log_suppressed() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.suppressed_at is not null then
    insert into lead_activity (lead_id, kind, body, metadata)
    values (new.id, 'suppressed', new.suppression_reason,
            jsonb_build_object('suppressed_at', new.suppressed_at));
  end if;
  return null;
end;
$$;

drop trigger if exists lead_suppressed_log on lead;
create trigger lead_suppressed_log after insert on lead
  for each row execute function lead_log_suppressed();

-- ---------------------------------------------------------------------------
-- RLS
--
-- Permissive: any authenticated user sees every lead. Policies are named for
-- what they will become, not for what they currently do, so tightening is
-- `alter policy lead_select_staff using (owner_id = auth.uid())` on a known
-- name rather than a rewrite.
--
-- owner_id is populated from day one even though nothing reads it for access
-- control. Ownership recorded only from the day it starts being enforced leaves
-- a null back catalogue you can never retroactively enforce on.
-- ---------------------------------------------------------------------------
alter table lead          enable row level security;
alter table lead_activity enable row level security;
alter table lead_status   enable row level security;
alter table suppression   enable row level security;

drop policy if exists lead_select_staff on lead;
create policy lead_select_staff on lead for select to authenticated using (true);

drop policy if exists lead_insert_staff on lead;
create policy lead_insert_staff on lead for insert to authenticated with check (true);

drop policy if exists lead_update_staff on lead;
create policy lead_update_staff on lead for update to authenticated
  using (true) with check (true);

drop policy if exists lead_delete_staff on lead;
create policy lead_delete_staff on lead for delete to authenticated using (true);

-- Append-only: no update policy, no delete policy. A wrong note is superseded,
-- not edited — the timeline is evidence.
drop policy if exists lead_activity_select_staff on lead_activity;
create policy lead_activity_select_staff on lead_activity
  for select to authenticated using (true);

drop policy if exists lead_activity_insert_staff on lead_activity;
create policy lead_activity_insert_staff on lead_activity
  for insert to authenticated
  with check (actor_id is null or actor_id = auth.uid());

drop policy if exists suppression_select_staff on suppression;
create policy suppression_select_staff on suppression
  for select to authenticated using (true);

drop policy if exists suppression_insert_staff on suppression;
create policy suppression_insert_staff on suppression
  for insert to authenticated with check (true);

drop policy if exists suppression_update_staff on suppression;
create policy suppression_update_staff on suppression
  for update to authenticated using (true) with check (true);

drop policy if exists suppression_delete_staff on suppression;
create policy suppression_delete_staff on suppression
  for delete to authenticated using (true);

drop policy if exists lead_status_select_staff on lead_status;
create policy lead_status_select_staff on lead_status
  for select to authenticated using (true);

-- ---------------------------------------------------------------------------
-- Views for the UI.
--
-- security_invoker = true is load-bearing. A Postgres view runs with its
-- OWNER's privileges by default, which would apply the owner's RLS rather than
-- the caller's — reintroducing the exact bypass the REST-resource decision
-- exists to prevent, through a back door that looks like a convenience.
-- ---------------------------------------------------------------------------
create or replace view lead_inbox with (security_invoker = true) as
  select l.id, l.source, l.status, s.label as status_label, l.owner_id,
         l.business_name, l.contact_name, l.email, l.phone, l.website,
         l.city, l.state, l.category,
         l.prospect_id, l.suppressed_at, l.suppression_reason,
         l.created_at, l.updated_at,
         (select count(*) from lead_activity a where a.lead_id = l.id) as activity_count
    from lead l
    join lead_status s on s.key = l.status
   where l.deleted_at is null;

create or replace view lead_detail with (security_invoker = true) as
  select l.*, s.label as status_label, p.name as prospect_name, p.place_id
    from lead l
    join lead_status s on s.key = l.status
    left join prospect p on p.id = l.prospect_id;

-- ---------------------------------------------------------------------------
-- Grants. RLS decides which rows; grants decide whether the role can reach the
-- table at all.
--
-- REVOKE FIRST. Supabase's default privileges already grant ALL on new public
-- tables to anon and authenticated, so a bare `grant select, insert` adds
-- nothing and removes nothing — it reads like a restriction while leaving
-- UPDATE, DELETE and TRUNCATE in place. Verified live before this was fixed.
-- Two things went wrong:
--
--   * append-only on lead_activity was resting entirely on the ABSENCE of an
--     update policy. An UPDATE with no matching policy is not an error — it
--     silently affects zero rows. So an "edit note" button in the UI would
--     report success and change nothing, which is worse than a refusal.
--   * TRUNCATE is not subject to row-level security at all. A role holding it
--     can empty the table regardless of every policy above.
-- ---------------------------------------------------------------------------
revoke all on lead, lead_activity, lead_status, suppression from anon, authenticated;
revoke all on lead_inbox, lead_detail from anon, authenticated;

grant select, insert, update, delete on lead          to authenticated;
grant select, insert                 on lead_activity to authenticated;  -- append-only
grant select, insert, update, delete on suppression   to authenticated;
grant select                         on lead_status   to authenticated;
grant select                         on lead_inbox, lead_detail to authenticated;

-- The trigger functions are SECURITY DEFINER (they write lead_activity on
-- behalf of a caller with no rights there). Living in `public` also made them
-- callable as RPC — /rest/v1/rpc/lead_flag_suppressed and friends. Invoking a
-- trigger function directly errors out, so it was not exploitable, but a
-- definer-rights function should not be reachable from the API at all.
revoke execute on function lead_flag_suppressed()  from anon, authenticated, public;
revoke execute on function lead_log_changes()      from anon, authenticated, public;
revoke execute on function lead_log_suppressed()   from anon, authenticated, public;
revoke execute on function lead_touch_updated_at() from anon, authenticated, public;
