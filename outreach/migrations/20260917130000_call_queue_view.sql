-- Migration: 20260917130000_call_queue_view.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Cold-caller CRM Tier 1.1 / 1.5 — the caller's triage surface. Creates `v_call_queue`
--            (today's phone call list, score-ordered) and enriches the already-live
--            `v_overdue_actions` so both are dial-ready when exposed as routes.
--
-- WHY THIS DIVERGES FROM crm-layer-spec.md §6's v_call_queue (deliberately, evidence in hand):
--
--   1. Score source. The spec joins `prospect_score where pass = 2 and model = 'value' and
--      channel = 'phone'`. Stage-1 scores the phone track at PASS 1 (no email enrichment yet), so
--      `pass = 2` would show a null score for every lead — the exact pitfall the Phase-4 migration
--      built `v_prospect_ranked` to avoid. This view reads the value score/decile/pitch from
--      `v_prospect_ranked` (channel = 'phone'), which resolves the correct pass and anchors on the
--      latest score_run per market. 342 real prospect_score rows exist, so the queue shows real
--      scores today.
--
--   2. Suppression gate. The spec's `not exists (… suppression s where s.prospect_id = …)` cannot
--      run here — the live `suppression` table has NO prospect_id column (id/scope/value/reason).
--      Suppression reaches a lead through the `lead_flag_suppressed` trigger, which stamps
--      `lead.suppressed_at` when the lead matches a suppression value. So the gate is
--      `l.suppressed_at is null` — the working, trigger-backed equivalent. It is intentionally
--      conservative: the trigger does not record which scope matched, so ANY suppression drops the
--      lead from the CALL queue. Over-excluding a suppressed lead is the safe error; calling one is
--      the unforgivable one (crm-layer-spec §4).
--
--   3. Extra columns the caller cockpit needs (T1.5): phone_type (mobile/landline — already
--      stored), lat/lng (so the UI can derive a local-time / business-hours hint when no zone is
--      stored), the new next_action_at/next_action_tz (the precise callback), last_disposition
--      (the structured value, not just the free-text call note the spec carried), and a
--      vendor_failing flag lifted from the scored factors.
--
-- security_invoker so the view runs with the querying role's rights (the service role platform-api
-- holds), matching v_prospect_ranked / v_prospect_placeholder_score. Read-only; no new tables.

create or replace view v_call_queue with (security_invoker = true) as
select
  l.id                              as lead_id,
  l.prospect_id,
  coalesce(p.name, l.company_name)  as name,
  coalesce(l.phone, p.phone)        as phone,
  p.phone_type,
  p.lat,
  p.lng,
  sm.name                           as submarket,
  l.source,
  l.stage,
  l.owner_id,
  l.next_action,
  l.next_action_due,
  l.next_action_at,
  l.next_action_tz,
  r.value_score                     as score,
  r.value_decile                    as decile,
  r.primary_pitch,
  -- Vendor-failing (scoring-spec's +79 signal): a vendor tag AND a measured decline. Detected by
  -- the stable bin name on the phone reply row of the SAME score_run the displayed score came from,
  -- so the flag can never disagree with the score beside it. Needs a delta (two snapshots), so it
  -- reads false on a first-scan market — honestly absent, never fabricated.
  coalesce((
    select true
      from prospect_score ps,
           lateral jsonb_array_elements(ps.score_factors) f
     where ps.prospect_id  = l.prospect_id
       and ps.score_run_id = r.score_run_id
       and ps.model = 'reply' and ps.channel = 'phone'
       and f->>'bin' in ('vendor_failing_pack', 'vendor_failing_organic')
     limit 1
  ), false)                         as vendor_failing,
  -- The structured disposition of the most recent touch that carried one (T1.5 — "last: voicemail").
  (select t.disposition from touch t
     where t.lead_id = l.id and t.disposition is not null
     order by t.touched_at desc limit 1) as last_disposition,
  -- The most recent call-note prose (the spec's last_call_note).
  (select a.body from lead_activity a
     where a.lead_id = l.id and a.kind = 'call_note'
     order by a.occurred_at desc limit 1) as last_call_note,
  -- An explicit sort key so the route can reproduce the queue order through PostgREST (which does
  -- not preserve a view's own ORDER BY): an un-dated lead ranks as if due today, not last.
  coalesce(l.next_action_due, current_date) as due_rank
from lead l
     left join prospect p         on p.id = l.prospect_id
     left join submarket sm       on sm.id = p.submarket_id
     left join v_prospect_ranked r on r.prospect_id = l.prospect_id and r.channel = 'phone'
where l.deleted_at is null
  and l.stage in ('new', 'contacted', 'replied', 'nurture')
  and l.suppressed_at is null
-- Due-date first (overdue/soonest rises), then the value score — the spec's ordering, so the
-- highest-value uncalled/overdue lead is row one. The route orders by (due_rank, score) to match.
order by due_rank, r.value_score desc nulls last;

comment on view v_call_queue is
  'Cold-caller CRM (T1.1/T1.5): today''s phone call list — workable-stage, non-suppressed leads, '
  'ordered by due-date then value score, carrying phone/phone_type, score/decile/primary_pitch, a '
  'vendor_failing flag, the precise callback (next_action_at/tz) and the last disposition. '
  'Corrects crm-layer-spec §6 for the live schema: score via v_prospect_ranked (not the stale '
  'pass=2 join), suppression via lead.suppressed_at (the suppression table has no prospect_id).';

-- v_overdue_actions already exists (spec §6, applied earlier); enrich it so the overdue list is
-- dial-ready — a caller working it needs the number and who it belongs to, not just a name. DROP
-- first: the new columns (prospect_id / phone / phone_type) land mid-list, and `create or replace`
-- can only append, not reorder. Safe — it is a view over live tables, holding no data of its own.
drop view if exists v_overdue_actions;
create or replace view v_overdue_actions with (security_invoker = true) as
select
  l.id                              as lead_id,
  l.prospect_id,
  coalesce(p.name, l.company_name)  as name,
  coalesce(l.phone, p.phone)        as phone,
  p.phone_type,
  l.source,
  l.owner_id,
  l.stage,
  l.next_action,
  l.next_action_due,
  l.next_action_at,
  l.next_action_tz,
  current_date - l.next_action_due  as days_overdue
from lead l
     left join prospect p on p.id = l.prospect_id
where l.next_action_due < current_date
  and l.stage not in ('won', 'lost')
  and l.deleted_at is null
  and l.suppressed_at is null
order by l.next_action_due;

comment on view v_overdue_actions is
  'Cold-caller CRM (T1.1): leads past their next_action_due that are neither won nor lost nor '
  'suppressed, soonest-overdue first. Enriched over crm-layer-spec §6 with prospect_id / phone / '
  'phone_type / the precise callback columns so the overdue list is dial-ready.';
