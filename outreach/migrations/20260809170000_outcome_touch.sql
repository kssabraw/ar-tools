-- Migration: 20260809170000_outcome_touch.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Phase 3 — the learning substrate. Creates `touch` (authoritative for
--            "a contact attempt happened") and `outcome` (the outbound-only
--            modelling substrate), and finally gives lead_activity.touch_id the
--            foreign key it has carried without one since Phase 1b.
--
-- WHY THIS EXISTS AND WHY NOW (scoring-spec.md §8, HANDOFF §12): `outcome` cannot
-- be backfilled — "MUST be written from campaign one even though nothing reads it
-- for months. Retrofitting it means the first hundred data points are lost
-- permanently." Every call placed before these tables exist is a prospect whose
-- result the Phase-4 model can never fit against. The suite is otherwise ready to
-- start calling.
--
-- The `outcome` DDL is adopted VERBATIM from PHASE3-outcome-constraint.md, which
-- was worked out and verified live against the real key with a throwaway probe
-- table. It is not re-derived here.

-- ---------------------------------------------------------------------------
-- touch — one contact attempt (a call placed, an email sent).
--
-- AUTHORITATIVE for "a contact attempt happened" (CLAUDE.md invariant).
-- `lead_activity` carries human commentary only and must never record a send —
-- which is why `lead_activity` has no 'call' / 'email_sent' kind and a call gets
-- a 'call_note' that REFERENCES the touch it comments on (the FK added in §3).
--
-- id is `bigint` because lead_activity.touch_id is bigint (Phase 1b shipped it
-- that way against this table's future existence). `generated always as identity`
-- so the id is the database's to mint, never a caller's.
--
-- Anchored on `lead`, not `prospect`: a touch happens against a lead (the CRM
-- entity being worked), lead_activity.touch_id lives on a lead's timeline, and an
-- inbound/referral lead can be contacted too. The outbound-only rule lives on
-- `outcome`, not here — a touch on an inbound lead is real and recordable; it
-- simply never rolls up into an outcome.
-- ---------------------------------------------------------------------------
create table if not exists touch (
  id               bigint generated always as identity primary key,
  lead_id          uuid not null references lead(id) on delete cascade,

  -- Phone and email are measured differently and never pooled in one model fit
  -- (scoring-spec.md §8 — separate offsets). The channel is a property of the
  -- attempt, so it lives here rather than on the outcome.
  channel          text not null check (channel in ('phone', 'email')),

  touched_at       timestamptz not null default now(),

  -- Which sequence this attempt belongs to, and which touch within it. Both
  -- nullable: a one-off manual dial has no sequence. `sequence_version` is the
  -- Phase-6 confounder-versioning stamp (scoring-spec §7a) captured at send time.
  sequence_version text,
  touch_number     smallint,

  -- Free text on purpose: the disposition vocabulary (no_answer / voicemail /
  -- connected / sent / bounced …) is still forming and a CHECK would need a
  -- migration to grow. It is descriptive, not a scored feature.
  disposition      text,
  note             text,

  -- AR Tools profile id of whoever logged the attempt. NO foreign key: profiles
  -- live in AR-Internal-Tools and Postgres cannot enforce a cross-database
  -- reference (HANDOFF §2 — same reasoning as lead.owner_id). Null = system.
  actor_id         uuid,

  created_at       timestamptz not null default now()
);

create index if not exists touch_lead_idx on touch (lead_id, touched_at desc);

-- ---------------------------------------------------------------------------
-- outcome — the modelling substrate. OUTBOUND-ONLY, ADOPTED VERBATIM from
-- PHASE3-outcome-constraint.md §1.
--
-- The outbound-only rule is made STRUCTURAL, not a trigger convention: the
-- composite FK targets lead(prospect_id, source), so a row can only attach to a
-- lead whose source is 'outbound_scan'. A promoted INBOUND lead also carries a
-- prospect_id (PHASE3-outcome-constraint.md), which is exactly why keying on
-- prospect alone cannot express the rule — the composite key can.
--
-- Three doors, all closed and verified live on 2026-07-31:
--   * outcome on an outbound lead                      → accepted
--   * outcome on an inbound lead with a prospect_id    → rejected (FK violation)
--   * reclassifying a lead that already has an outcome → rejected (the check
--     fires through `on update cascade`; without the cascade you could flip a
--     lead to inbound and strand its outcomes).
--
-- ⚠ 'outbound_scan' must match lead.source EXACTLY. It is a string literal in a
-- check constraint, so a typo does not fail loudly — it makes the table
-- permanently unwritable. If the source vocabulary is ever renamed, this
-- constraint and lead's source check must change in the SAME migration.
-- ---------------------------------------------------------------------------
create table if not exists outcome (
  prospect_id uuid primary key references prospect(id) on delete cascade,

  -- Denormalised so the composite FK below has something to constrain. Never
  -- written by hand: the check pins it, the FK proves it.
  lead_source text not null default 'outbound_scan'
    constraint outcome_outbound_only check (lead_source = 'outbound_scan'),

  -- Set when the FIRST touch is recorded, not at emit — a touch is authoritative
  -- for "a contact attempt happened", and emit only enqueues. So a prospect
  -- queued but never dialed keeps first_contacted_at null, which is the honest
  -- state the model needs to distinguish "queued" from "contacted".
  first_contacted_at timestamptz,

  -- thompson | random_control (scoring-spec §7); 'manual' for the pre-Phase-4
  -- hand-selection era (see the migration note / DECISIONS.md). NOT constrained
  -- here, deliberately (per the adopted DDL): the vocabulary can evolve without a
  -- migration, and the application validates it. Recorded on 100% of contacts.
  selection_reason text not null,

  sequence_version text not null,
  touches_per_sequence_at_send smallint not null,

  -- Maintained as a rollup of `touch` by the application (recompute-on-write, no
  -- trigger) so it can never drift from the touch rows it counts.
  touch_count integer not null default 0,

  replied_at timestamptz,
  first_response_at timestamptz,
  closed_at timestamptz,
  retainer_actual numeric,
  churned_at timestamptz,

  -- Additive audit columns (not in the modelling shape, so they never touch a
  -- coefficient): when the outcome row was created / last touched by the app.
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint outcome_lead_fk foreign key (prospect_id, lead_source)
    references lead (prospect_id, source) on update cascade on delete cascade
);

create or replace function outcome_touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists outcome_updated_at on outcome;
create trigger outcome_updated_at before update on outcome
  for each row execute function outcome_touch_updated_at();

-- ---------------------------------------------------------------------------
-- lead_activity.touch_id — give it the foreign key it has waited for.
--
-- PHASE3-outcome-constraint.md §2: check for orphans first (nothing enforced
-- this in the meantime). Verified 0 orphans live on 2026-08-09 before applying.
-- ON DELETE SET NULL: deleting a touch must not delete the human note that
-- commented on it — the note is commentary that outlives the attempt record.
-- The lead_activity_touch_on_call_note_only check (Phase 1b) already keeps a
-- touch_id off anything but a call_note.
-- ---------------------------------------------------------------------------
alter table lead_activity drop constraint if exists lead_activity_touch_fk;
alter table lead_activity
  add constraint lead_activity_touch_fk
  foreign key (touch_id) references touch(id) on delete set null;

-- ---------------------------------------------------------------------------
-- Access model → suite standard (HANDOFF §2). RLS ENABLED, ZERO policies, no
-- grants to anon/authenticated: reachable only through the service role
-- platform-api holds. REVOKE FIRST — Supabase grants ALL on new public tables to
-- anon/authenticated by default, so a bare grant reads like a restriction and
-- removes nothing (§6.12).
-- ---------------------------------------------------------------------------
alter table touch   enable row level security;
alter table outcome enable row level security;
revoke all on touch   from anon, authenticated;
revoke all on outcome from anon, authenticated;

-- The updated_at trigger function is a plain (non-definer) function and touches
-- only NEW, so it needs no execute grant to anyone — but revoke to match house
-- posture (nothing in public should be RPC-reachable unless it must be).
revoke execute on function outcome_touch_updated_at() from anon, authenticated, public;
