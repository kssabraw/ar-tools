-- Migration: 20260731190000_lead_crm_spec_reconcile.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Reconcile the Phase 1b CRM to docs/crm-layer-spec.md §3 (ISSUES.md
--            R-012), and repoint its access model at the suite-module decision.
--
-- Safe to be this aggressive — lead and lead_activity hold ZERO rows. Columns
-- are renamed and vocabularies replaced outright rather than dual-written. If
-- this ever runs against real data it will need a rewrite, not a re-run.
--
-- TWO THINGS CHANGED SINCE THE ORIGINAL MIGRATION
--
-- 1. The spec that owns these tables arrived. Phase 1b was built from a plan
--    derived from it; several vocabularies were guessed and guessed wrong. The
--    worst was `source`, which could not express a MANUAL lead — the phase's
--    primary use case.
--
-- 2. The outreach pipeline became an AR Tools suite module (owner ruling,
--    2026-07-31). The database stays here; the API and UI move into
--    platform-api and the suite SPA. That reverses the access model:
--
--      * Retool no longer connects directly, so per-user RLS policies are
--        unreachable code. These tables revert to the suite-standard posture —
--        RLS enabled, no policies, no grants to anon/authenticated, reached
--        only through the service role held by platform-api.
--      * Staff identities live in AR-Internal-Tools, a DIFFERENT database.
--        A foreign key to this project's auth.users can therefore never be
--        satisfied — that pool will stay empty forever. owner_id / actor_id /
--        created_by become unenforced uuids carrying the SUITE's profile id,
--        validated by platform-api instead of by Postgres.
--
--    Dropping those FKs is a real loss of integrity, accepted knowingly: the
--    alternative is a column that is either always null or lying.

-- ---------------------------------------------------------------------------
-- 1. Stage vocabulary → spec §3 `lead_stage`
--
-- Kept as a lookup table rather than the spec's enum: the board needs
-- sort_order to lay out columns and is_terminal to decide what stops a lead,
-- and neither survives in an enum. The VALUES are now the spec's, which is what
-- actually mattered.
--
-- 'qualified' is gone. §8a records a deliberate decision to collapse it into
-- 'in_conversation' so two stage vocabularies never coexist in one analysis;
-- the original migration reintroduced it, which is precisely the outcome that
-- decision exists to prevent. 'disqualified' is gone too — it is a LOST REASON
-- in the spec, not a stage, and having it in both places would split the same
-- fact across two columns.
-- ---------------------------------------------------------------------------
alter table lead_status rename to lead_stage;
alter table lead rename column status to stage;

-- Rewrite the vocabulary wholesale. Safe: no lead rows reference these.
delete from lead_stage;
insert into lead_stage (key, label, sort_order, is_terminal) values
  ('new',             'New',             0, false),
  ('contacted',       'Contacted',       1, false),
  ('replied',         'Replied',         2, false),
  ('in_conversation', 'In conversation', 3, false),
  ('won',             'Won',             4, true),
  ('lost',            'Lost',            5, true),
  ('nurture',         'Nurture',         6, false);

-- ---------------------------------------------------------------------------
-- 2. `source` → spec §3 `lead_source` (six values)
--
-- The original check held ('outbound_scan','inbound','referral'). 'inbound' is
-- not a spec token at all, and 'manual' and 'partner' were missing — so a hand
-- entered lead, which is the whole point of running this track in parallel with
-- Phase 1, could not be recorded.
--
-- 'outbound_scan' is unchanged and must stay exact: Phase 3's outcome check
-- constraint compares against this literal, so drift there makes `outcome`
-- permanently unwritable rather than failing loudly.
-- ---------------------------------------------------------------------------
alter table lead drop constraint if exists lead_source_check;
alter table lead add constraint lead_source_check check (source in (
  'outbound_scan', 'inbound_form', 'inbound_call', 'referral', 'manual', 'partner'
));

-- ---------------------------------------------------------------------------
-- 3. Column names → spec §3
-- ---------------------------------------------------------------------------
alter table lead rename column business_name to company_name;
alter table lead rename column notes          to notes_intake;

-- ---------------------------------------------------------------------------
-- 4. The workflow fields that were missing entirely
--
-- lost_reason is the highest-value field in the layer (§5): each value tests a
-- named scoring coefficient, and it is captured at the one moment a human
-- already knows the answer. Unrecoverable afterwards.
--
-- A CHECK rather than a lookup table, deliberately diverging from how stage is
-- modelled above. Stages are presentation — they need labels and ordering, and
-- adding one is a workflow tweak. Lost reasons are ANALYSIS: each is joined to
-- a coefficient, so adding one silently changes what a refit means. Making that
-- a migration rather than an insert is the point.
-- ---------------------------------------------------------------------------
alter table lead add column if not exists lost_reason      text;
alter table lead add column if not exists lost_to          text;   -- named competitor
alter table lead add column if not exists next_action      text;
alter table lead add column if not exists next_action_due  date;
alter table lead add column if not exists stage_changed_at timestamptz not null default now();

alter table lead drop constraint if exists lead_lost_reason_check;
alter table lead add constraint lead_lost_reason_check check (lost_reason is null or lost_reason in (
  'no_response', 'not_interested', 'no_budget', 'has_agency', 'timing',
  'went_elsewhere', 'disqualified', 'unreachable', 'opted_out'
));

-- §5: "a lost lead without a reason is a lost label, and labels are the point."
alter table lead drop constraint if exists lost_requires_reason;
alter table lead add constraint lost_requires_reason
  check (stage <> 'lost' or lost_reason is not null);

-- §3: outbound leads always came from a scanned prospect.
alter table lead drop constraint if exists outbound_requires_prospect;
alter table lead add constraint outbound_requires_prospect
  check (source <> 'outbound_scan' or prospect_id is not null);

-- §3: a lead with no prospect behind it still has to be identifiable.
alter table lead drop constraint if exists non_prospect_needs_identity;
alter table lead add constraint non_prospect_needs_identity
  check (prospect_id is not null or company_name is not null);

create index if not exists lead_next_action_due_idx
  on lead (next_action_due) where next_action_due is not null;

-- ---------------------------------------------------------------------------
-- 5. Identity columns lose their foreign keys (see header note 2)
-- ---------------------------------------------------------------------------
alter table lead          drop constraint if exists lead_owner_id_fkey;
alter table lead          drop constraint if exists lead_created_by_fkey;
alter table lead_activity drop constraint if exists lead_activity_actor_id_fkey;
alter table suppression   drop constraint if exists suppression_created_by_fkey;

comment on column lead.owner_id is
  'AR Tools profile id (AR-Internal-Tools project). Deliberately no FK: that '
  'table lives in a different database. platform-api validates it.';
comment on column lead_activity.actor_id is
  'AR Tools profile id; null means the system acted. No FK — cross-database.';

-- ---------------------------------------------------------------------------
-- 6. lead_activity → spec §3
--
-- from_stage/to_stage become real columns. They were being written into
-- metadata, which left the acceptance criterion ("stage changes always write a
-- row with from/to") true in spirit but unverifiable by query.
--
-- Kinds are the spec's set. 'assignment' and 'suppressed' are dropped in favour
-- of 'system' carrying the detail in metadata — the spec's list is closed, and
-- inventing kinds is how two timelines stop being comparable.
-- ---------------------------------------------------------------------------
alter table lead_activity add column if not exists from_stage text;
alter table lead_activity add column if not exists to_stage   text;

alter table lead_activity drop constraint if exists lead_activity_kind_check;
alter table lead_activity add constraint lead_activity_kind_check check (kind in (
  'note', 'call_note', 'email_reply', 'meeting',
  'proposal', 'stage_change', 'asset_viewed', 'system'
));

-- ---------------------------------------------------------------------------
-- 7. suppression — remove the deletion path and the expiry
--
-- §4 and the acceptance criteria: "Suppression records MUST NOT be deleted,
-- ever. Deletion re-opens the prospect on the next cycle, which is both a
-- compliance failure and a reputational one." The original migration granted
-- DELETE and shipped a delete policy.
--
-- expires_at goes with it. It had no basis in the spec, and a time-limited
-- suppression is a soft delete of a record the spec treats as permanent —
-- someone who said "never contact me again" does not mean "not for 90 days".
-- ---------------------------------------------------------------------------
alter table suppression drop column if exists expires_at;

-- ---------------------------------------------------------------------------
-- 8. Triggers updated for the new column names
-- ---------------------------------------------------------------------------
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

  -- No expiry filter any more: suppression is permanent by decision.
  select * into hit from suppression s where s.value = any (candidates) limit 1;

  if found then
    new.suppressed_at      := now();
    new.suppression_reason := coalesce(hit.reason, 'matched suppression: ' || hit.scope);
  end if;

  return new;
end;
$$;

create or replace function lead_log_changes() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.stage is distinct from old.stage then
    insert into lead_activity (lead_id, actor_id, kind, body, from_stage, to_stage)
    values (new.id, auth.uid(), 'stage_change',
            format('Stage %s → %s', old.stage, new.stage), old.stage, new.stage);
  end if;

  if new.owner_id is distinct from old.owner_id then
    insert into lead_activity (lead_id, actor_id, kind, body, metadata)
    values (new.id, auth.uid(), 'system',
            case when new.owner_id is null then 'Unassigned' else 'Assigned' end,
            jsonb_build_object('event', 'assignment',
                               'from', old.owner_id, 'to', new.owner_id));
  end if;

  return null;
end;
$$;

create or replace function lead_log_suppressed() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.suppressed_at is not null then
    insert into lead_activity (lead_id, kind, body, metadata)
    values (new.id, 'system', new.suppression_reason,
            jsonb_build_object('event', 'suppressed',
                               'suppressed_at', new.suppressed_at));
  end if;
  return null;
end;
$$;

-- stage_changed_at is maintained here rather than in application code so it
-- stays true no matter which write path moves the lead.
create or replace function lead_touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  if new.stage is distinct from old.stage then
    new.stage_changed_at := now();
  end if;
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- 9. Access model → suite standard
--
-- Every policy is dropped and every grant revoked. RLS stays ENABLED with no
-- policies, which is the posture of every other table in the estate: the
-- service role bypasses RLS, and nothing else can reach the table at all.
-- Authorization moves up into platform-api, next to the suite's existing
-- role checks.
--
-- Keeping the permissive policies would be worse than useless — they would
-- read as an access model while granting full table access to anyone holding
-- an anon or authenticated JWT for this project.
-- ---------------------------------------------------------------------------
drop policy if exists lead_select_staff            on lead;
drop policy if exists lead_insert_staff            on lead;
drop policy if exists lead_update_staff            on lead;
drop policy if exists lead_delete_staff            on lead;
drop policy if exists lead_activity_select_staff   on lead_activity;
drop policy if exists lead_activity_insert_staff   on lead_activity;
drop policy if exists suppression_select_staff     on suppression;
drop policy if exists suppression_insert_staff     on suppression;
drop policy if exists suppression_update_staff     on suppression;
drop policy if exists suppression_delete_staff     on suppression;
drop policy if exists lead_status_select_staff     on lead_stage;

revoke all on lead, lead_activity, lead_stage, suppression from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 10. Views
--
-- security_invoker is no longer load-bearing (there is no per-user caller any
-- more) but is kept: it costs nothing and means these views never silently
-- acquire their owner's privileges if policies are ever reintroduced.
--
-- v_overdue_actions is added now that next_action_due exists. §10 designates it
-- the forcing function for manual reply capture — the thing that makes someone
-- notice a lead has gone quiet. It is the one spec view whose dependencies all
-- exist today.
-- ---------------------------------------------------------------------------
drop view if exists lead_inbox;
drop view if exists lead_detail;

create view lead_inbox with (security_invoker = true) as
  select l.id, l.source, l.stage, s.label as stage_label, l.owner_id,
         l.company_name, l.contact_name, l.email, l.phone, l.website,
         l.city, l.state, l.category,
         l.next_action, l.next_action_due,
         l.prospect_id, l.suppressed_at, l.suppression_reason,
         l.stage_changed_at, l.created_at, l.updated_at,
         (select count(*) from lead_activity a where a.lead_id = l.id) as activity_count
    from lead l
    join lead_stage s on s.key = l.stage
   where l.deleted_at is null;

create view lead_detail with (security_invoker = true) as
  select l.*, s.label as stage_label, p.name as prospect_name, p.place_id
    from lead l
    join lead_stage s on s.key = l.stage
    left join prospect p on p.id = l.prospect_id;

create view v_overdue_actions with (security_invoker = true) as
  select l.id as lead_id, coalesce(p.name, l.company_name) as name, l.source,
         l.owner_id, l.stage, l.next_action, l.next_action_due,
         current_date - l.next_action_due as days_overdue
    from lead l
    left join prospect p on p.id = l.prospect_id
   where l.next_action_due < current_date
     and l.stage not in ('won', 'lost')
     and l.deleted_at is null
   order by l.next_action_due;

revoke all on lead_inbox, lead_detail, v_overdue_actions from anon, authenticated;
