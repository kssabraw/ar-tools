-- Verification script for the Phase 3 `outcome` + `touch` tables and the
-- lead_activity.touch_id foreign key (migration 20260809170000).
-- Target: Outreacher (fkwhgvcggvsricuinuqy).
--
-- Run as the service role (Supabase SQL editor, or the MCP execute_sql tool).
-- It creates its own fixtures and deletes them at the end. Every line prints
-- `(correct)` or `(WRONG)`; any WRONG is a regression.
--
-- Companion to tests/lead_crm_rls.sql, same shape and philosophy. This one
-- proves the three doors PHASE3-outcome-constraint.md set out — outbound
-- accepted, inbound-with-a-prospect_id rejected, reclassify-with-an-outcome
-- rejected — plus the touch/lead_activity wiring and the house access posture.
--
-- Sections:
--   A. outcome constraints and touch behaviour, as the service role.
--   B. The access model — anon and authenticated must reach neither table.

create temp table result (n int, note text) on commit drop;
grant insert, select on result to authenticated, anon;

-- ===========================================================================
-- A. outcome + touch behaviour
-- ===========================================================================
do $$
declare
  p_out uuid; p_in uuid; lead_out uuid; lead_in uuid; tid bigint; act uuid; r record;
begin
  -- Two distinct prospects with NO existing lead (the unique (prospect_id) index
  -- means a prospect already promoted cannot take a second lead — pick fresh
  -- ones so the fixture never collides with real data). One becomes an outbound
  -- lead, one an inbound lead that still carries a prospect_id (the exact case
  -- keying on prospect alone could not distinguish).
  select id into p_out from prospect
    where id not in (select prospect_id from lead where prospect_id is not null)
    order by id limit 1;
  select id into p_in from prospect
    where id not in (select prospect_id from lead where prospect_id is not null)
      and id <> p_out
    order by id limit 1;

  insert into lead (source, company_name, prospect_id)
    values ('outbound_scan', '__t OutLead', p_out) returning id into lead_out;
  insert into lead (source, company_name, prospect_id)
    values ('inbound_form',  '__t InLead',  p_in)  returning id into lead_in;

  -- 1. An outcome on an outbound lead is accepted.
  insert into outcome (prospect_id, selection_reason, sequence_version,
                       touches_per_sequence_at_send)
    values (p_out, 'manual', 'phone_v1', 5);
  insert into result values (1, '1. outcome on an outbound lead accepted (correct)');

  -- 2. An outcome on an INBOUND lead that has a prospect_id is rejected by the
  --    composite FK — there is no lead(prospect_id, 'outbound_scan') for it.
  begin
    insert into outcome (prospect_id, selection_reason, sequence_version,
                         touches_per_sequence_at_send)
      values (p_in, 'manual', 'phone_v1', 5);
    insert into result values (2, '2. outcome on an inbound-with-prospect lead accepted (WRONG)');
  exception when foreign_key_violation then
    insert into result values (2, '2. outcome on an inbound-with-prospect lead rejected by FK (correct)');
  end;

  -- 3. Reclassifying a lead that already has an outcome is rejected: the
  --    on-update-cascade tries to rewrite outcome.lead_source, the outbound-only
  --    check refuses, and the whole update fails. This is the back door a plain
  --    FK would leave open.
  begin
    update lead set source = 'manual' where id = lead_out;
    insert into result values (3, '3. reclassifying a lead with an outcome accepted (WRONG)');
  exception when check_violation then
    insert into result values (3, '3. reclassifying a lead with an outcome rejected (correct)');
  end;

  -- 4. lead_source is pinned to 'outbound_scan' — a hand-written other value is
  --    refused by the check even on insert.
  begin
    insert into outcome (prospect_id, lead_source, selection_reason,
                         sequence_version, touches_per_sequence_at_send)
      values (p_in, 'inbound_form', 'manual', 'phone_v1', 5);
    insert into result values (4, '4. outcome with a non-outbound lead_source accepted (WRONG)');
  exception when check_violation or foreign_key_violation then
    insert into result values (4, '4. outcome with a non-outbound lead_source rejected (correct)');
  end;

  -- 5. A touch on a lead is accepted, and a call_note may reference it.
  insert into touch (lead_id, channel, disposition)
    values (lead_out, 'phone', 'connected') returning id into tid;
  insert into lead_activity (lead_id, kind, body, touch_id)
    values (lead_out, 'call_note', 'spoke to the owner', tid) returning id into act;
  insert into result values (5, '5. touch written and referenced by a call_note (correct)');

  -- 6. touch_id is only meaningful on a call_note (Phase 1b check, re-proven now
  --    that a real touch exists to point at).
  begin
    insert into lead_activity (lead_id, kind, body, touch_id)
      values (lead_out, 'note', 'x', tid);
    insert into result values (6, '6. touch_id accepted on a plain note (WRONG)');
  exception when check_violation then
    insert into result values (6, '6. touch_id rejected on a plain note (correct)');
  end;

  -- 7. Deleting a touch nulls the referencing note's touch_id (ON DELETE SET
  --    NULL), never deleting the human commentary.
  delete from touch where id = tid;
  select touch_id into r from lead_activity where id = act;
  if r.touch_id is null and exists (select 1 from lead_activity where id = act) then
    insert into result values (7, '7. deleting a touch nulls the note''s touch_id, note survives (correct)');
  else
    insert into result values (7, '7. touch delete did not SET NULL / lost the note (WRONG)');
  end if;

  -- 8. Deleting the lead cascades to its outcome (ON DELETE CASCADE): the
  --    modelling row does not outlive the lead it belongs to.
  delete from lead where id = lead_out;
  if not exists (select 1 from outcome where prospect_id = p_out) then
    insert into result values (8, '8. deleting the lead cascaded away its outcome (correct)');
  else
    insert into result values (8, '8. outcome survived its lead being deleted (WRONG)');
  end if;

  -- Cleanup: lead_out is gone (its touch/activity/outcome cascaded); remove the
  -- inbound fixture too.
  delete from lead where id = lead_in;
  delete from lead where company_name like '__t %';
end $$;

-- ===========================================================================
-- B. Access model — anon and authenticated must reach neither table
-- ===========================================================================
do $$
declare n int;
begin
  set local role authenticated;
  set local request.jwt.claims = '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

  begin
    select count(*) into n from outcome;
    insert into result values (9, format('9. authenticated reads outcome -> %s rows (WRONG, should be denied)', n));
  exception when insufficient_privilege then
    insert into result values (9, '9. authenticated cannot read outcome (correct)');
  end;

  begin
    select count(*) into n from touch;
    insert into result values (10, format('10. authenticated reads touch -> %s rows (WRONG)', n));
  exception when insufficient_privilege then
    insert into result values (10, '10. authenticated cannot read touch (correct)');
  end;

  -- TRUNCATE ignores row-level security; only the revoked grant stops it.
  begin
    execute 'truncate outcome cascade';
    insert into result values (11, '11. authenticated truncated outcome (WRONG)');
  exception when insufficient_privilege then
    insert into result values (11, '11. authenticated cannot truncate outcome (correct)');
  end;

  reset role;
end $$;

do $$
declare n int;
begin
  set local role anon;
  begin
    select count(*) into n from touch;
    insert into result values (12, format('12. anon reads touch -> %s rows (WRONG)', n));
  exception when insufficient_privilege then
    insert into result values (12, '12. anon cannot read touch (correct)');
  end;
  reset role;
end $$;

select n, note from result order by n;
