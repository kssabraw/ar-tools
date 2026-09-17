-- Migration: 20260917140000_cadence_and_scoreboard.sql
-- Target:    Outreacher project (fkwhgvcggvsricuinuqy) — NOT AR-Internal-Tools.
-- Purpose:   Cold-caller CRM Tier 2.1 (cadence) + 2.2 (caller scoreboard). Adds a per-lead touch
--            rollup (`v_lead_cadence`) surfaced on the queue/overdue/board cards, and a windowed
--            per-caller aggregate function (`outreach_caller_scoreboard`) behind the scoreboard.
--            Read-only: one view + two view updates + one stable function. No new tables, no writes.
--
-- WHY A FUNCTION FOR THE SCOREBOARD (not a view): the scoreboard is always over a TIME WINDOW
-- (today / last 7 / last 30 days), and a view cannot take a parameter. Aggregating in the app would
-- mean pulling every touch in the window over the wire — an unbounded read PostgREST silently caps
-- at 1,000 (outreach ISSUES I-036, the exact trap this codebase forbids). A `stable` SQL function
-- returns ONE row per caller regardless of touch volume, server-side, so it can never truncate.
--
-- WHY THE VIEW UPDATES ONLY APPEND: `create or replace view` keeps the leading column list (names,
-- types, order) byte-identical and appends new columns at the end — so v_call_queue / v_overdue_actions
-- gain cadence columns without a drop, and nothing that reads their existing columns changes.

-- Per-lead cadence rollup (T2.1): how many contact attempts, when the last one was, and its
-- structured disposition — "attempt 3 of 5 · last: voicemail Tue". security_invoker so it runs with
-- the querying (service) role's rights, matching v_call_queue / v_prospect_ranked.
create or replace view v_lead_cadence with (security_invoker = true) as
select
  t.lead_id,
  count(*)                                        as attempt_count,
  max(t.touched_at)                               as last_touched_at,
  -- Most recent touch that carried a structured disposition (a note-only touch has none). array_agg
  -- desc-by-time then [1] is the newest non-null — the same "last disposition" v_call_queue computes.
  (array_agg(t.disposition order by t.touched_at desc)
     filter (where t.disposition is not null))[1] as last_disposition
from touch t
group by t.lead_id;

comment on view v_lead_cadence is
  'Cold-caller CRM (T2.1): per-lead touch rollup — attempt_count, last_touched_at, last_disposition. '
  'Joined onto v_call_queue / v_overdue_actions and read per-page for the board so every card can '
  'show call cadence ("attempt N of 5 · last: voicemail").';

-- v_call_queue gains cadence (append-only; the full definition is reproduced because create-or-replace
-- needs the whole SELECT). Leading columns are byte-identical to 20260917130000; only the LEFT JOIN
-- to v_lead_cadence and the two trailing columns are new.
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
  (select t.disposition from touch t
     where t.lead_id = l.id and t.disposition is not null
     order by t.touched_at desc limit 1) as last_disposition,
  (select a.body from lead_activity a
     where a.lead_id = l.id and a.kind = 'call_note'
     order by a.occurred_at desc limit 1) as last_call_note,
  coalesce(l.next_action_due, current_date) as due_rank,
  -- T2.1 cadence (appended): how many attempts so far and when the last one landed. coalesce so an
  -- un-touched lead reads 0, not null, on the card.
  coalesce(lc.attempt_count, 0)     as attempt_count,
  lc.last_touched_at
from lead l
     left join prospect p          on p.id = l.prospect_id
     left join submarket sm        on sm.id = p.submarket_id
     left join v_prospect_ranked r on r.prospect_id = l.prospect_id and r.channel = 'phone'
     left join v_lead_cadence lc   on lc.lead_id = l.id
where l.deleted_at is null
  and l.stage in ('new', 'contacted', 'replied', 'nurture')
  and l.suppressed_at is null
order by due_rank, r.value_score desc nulls last;

comment on view v_call_queue is
  'Cold-caller CRM (T1.1/T1.5/T2.1): today''s phone call list — workable-stage, non-suppressed leads, '
  'ordered by due-date then value score, carrying phone/phone_type, score/decile/primary_pitch, a '
  'vendor_failing flag, the precise callback (next_action_at/tz), the last disposition, and (T2.1) '
  'attempt_count / last_touched_at for call cadence. Corrects crm-layer-spec §6 for the live schema: '
  'score via v_prospect_ranked (not the stale pass=2 join), suppression via lead.suppressed_at.';

-- v_overdue_actions gains the same cadence columns (append-only).
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
  current_date - l.next_action_due  as days_overdue,
  -- T2.1 cadence (appended).
  coalesce(lc.attempt_count, 0)     as attempt_count,
  lc.last_touched_at,
  lc.last_disposition
from lead l
     left join prospect p        on p.id = l.prospect_id
     left join v_lead_cadence lc on lc.lead_id = l.id
where l.next_action_due < current_date
  and l.stage not in ('won', 'lost')
  and l.deleted_at is null
  and l.suppressed_at is null
order by l.next_action_due;

comment on view v_overdue_actions is
  'Cold-caller CRM (T1.1/T2.1): leads past their next_action_due that are neither won nor lost nor '
  'suppressed, soonest-overdue first. Carries prospect_id / phone / phone_type / the precise callback '
  'columns (dial-ready) plus attempt_count / last_touched_at / last_disposition for cadence.';

-- Windowed per-caller aggregate (T2.2). One row per actor who logged a touch since `since`. Every
-- metric is derived from touches + their structured dispositions — the vocabulary T1.2 made countable.
-- `dials` counts phone attempts only (an email send is not a dial); `conversations` = a live person
-- reached (connected or decision_maker). Meetings-booked is deliberately absent: there is no such
-- disposition in the set, and inferring one from stage would mix the outbound-only touch substrate
-- with workflow state. connect_rate is left to the app (a ratio, not a count).
create or replace function outreach_caller_scoreboard(since timestamptz)
returns table (
  actor_id        uuid,
  dials           bigint,
  conversations   bigint,
  dm_reached      bigint,
  callbacks       bigint,
  voicemails      bigint,
  not_interested  bigint,
  dnc             bigint,
  touches         bigint,
  last_touch_at   timestamptz
)
language sql
stable
security invoker
as $$
  select
    t.actor_id,
    count(*) filter (where t.channel = 'phone')                              as dials,
    count(*) filter (where t.disposition in ('connected', 'decision_maker')) as conversations,
    count(*) filter (where t.disposition = 'decision_maker')                 as dm_reached,
    count(*) filter (where t.disposition = 'callback_requested')             as callbacks,
    count(*) filter (where t.disposition = 'voicemail')                      as voicemails,
    count(*) filter (where t.disposition = 'not_interested')                 as not_interested,
    count(*) filter (where t.disposition = 'do_not_call')                    as dnc,
    count(*)                                                                 as touches,
    max(t.touched_at)                                                        as last_touch_at
  from touch t
  where t.touched_at >= since
    and t.actor_id is not null
  group by t.actor_id;
$$;

comment on function outreach_caller_scoreboard(timestamptz) is
  'Cold-caller CRM (T2.2): per-caller touch/disposition aggregate over [since, now]. One row per '
  'actor_id; the caller''s name is resolved app-side against AR-Internal-Tools profiles (a different '
  'project). connect_rate is computed by the app from conversations/dials. Server-side aggregation '
  'so the read cannot truncate on touch volume the way an app-side count would.';
