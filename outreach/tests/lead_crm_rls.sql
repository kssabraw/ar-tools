-- Verification script for the Phase 1b lead CRM, post spec-reconcile (ISSUES.md R-012).
-- Target: Outreacher (fkwhgvcggvsricuinuqy).
--
-- Run as the service role (Supabase SQL editor, or the MCP execute_sql tool).
-- It creates its own fixtures and deletes them at the end. Every line prints
-- `(correct)` or `(WRONG)`; any WRONG is a regression.
--
-- Why a script and not a test suite: the repo has no database test harness, and
-- adding pgTAP would be new infrastructure. This is deliberately the cheapest
-- thing that actually exercises the constraints rather than asserting they
-- exist in the catalogue.
--
-- Sections, and note they assert OPPOSITE things about the same tables:
--   A. Schema and behaviour (1-12), as the service role — the identity
--      platform-api actually uses.
--   B. The access model (13-17). Since the outreach pipeline became an AR Tools
--      suite module, these tables are reached ONLY through platform-api's
--      service role, so anon and authenticated must be able to do NOTHING.
--
-- Section B is the exact INVERSE of what this file asserted before the module
-- ruling. The earlier version verified a permissive per-user RLS model built
-- for a direct Retool connection; that connection no longer exists, so those
-- policies were dropped rather than left lying around looking load-bearing.

create temp table result (n int, note text) on commit drop;
grant insert, select on result to authenticated, anon;

-- ===========================================================================
-- A. Schema and behaviour
-- ===========================================================================
do $$
declare
  lid uuid; outbound_p uuid; r record; before_ts timestamptz; after_ts timestamptz;
begin
  select id into outbound_p from prospect limit 1;

  -- 1. A hand-entered lead. Impossible before the reconcile: the old source
  --    check held ('outbound_scan','inbound','referral'), and manual entry is
  --    the primary reason this track runs in parallel with Phase 1 at all.
  insert into lead (source, company_name) values ('manual', '__t Manual') returning id into lid;
  insert into result values (1, '1. manual lead accepted (correct)');

  -- 2. The tokens the original migration guessed must now be rejected.
  begin
    insert into lead (source, company_name) values ('inbound', '__t Stale');
    insert into result values (2, '2. stale token ''inbound'' accepted (WRONG)');
  exception when check_violation then
    insert into result values (2, '2. stale token ''inbound'' rejected (correct)');
  end;

  -- 3. spec §3 outbound_requires_prospect.
  begin
    insert into lead (source, company_name) values ('outbound_scan', '__t NoProspect');
    insert into result values (3, '3. outbound lead with no prospect accepted (WRONG)');
  exception when check_violation then
    insert into result values (3, '3. outbound lead with no prospect rejected (correct)');
  end;

  -- 4. spec §3 non_prospect_needs_identity — a lead nobody can identify is noise.
  begin
    insert into lead (source, email) values ('inbound_form', 'x@y.com');
    insert into result values (4, '4. lead with neither prospect nor company accepted (WRONG)');
  exception when check_violation then
    insert into result values (4, '4. lead with neither prospect nor company rejected (correct)');
  end;

  -- 5. spec §5: a lost lead without a reason is a lost label, and the labels
  --    are the point — each one tests a named scoring coefficient.
  begin
    update lead set stage = 'lost' where id = lid;
    insert into result values (5, '5. lost without a reason accepted (WRONG)');
  exception when check_violation then
    insert into result values (5, '5. lost without a reason rejected (correct)');
  end;

  -- 6. Stage changes land on the timeline in the spec's from_stage/to_stage
  --    COLUMNS, not buried in metadata where no query can check the criterion.
  update lead set stage = 'lost', lost_reason = 'no_budget' where id = lid;
  select from_stage, to_stage into r
    from lead_activity where lead_id = lid and kind = 'stage_change';
  if r.from_stage = 'new' and r.to_stage = 'lost' then
    insert into result values (6, '6. stage change logged new->lost in from/to columns (correct)');
  else
    insert into result values (6, format('6. stage change logged as %s->%s (WRONG)', r.from_stage, r.to_stage));
  end if;

  -- 7. stage_changed_at. Backdated first, because now() is TRANSACTION time in
  --    Postgres — comparing it against created_at inside one transaction shows
  --    no movement whether the trigger fired or not. That false failure is what
  --    invites someone to "fix" a trigger that works.
  update lead set stage_changed_at = now() - interval '10 days' where id = lid;
  select stage_changed_at into before_ts from lead where id = lid;
  update lead set stage = 'nurture', lost_reason = null where id = lid;
  select stage_changed_at into after_ts from lead where id = lid;
  if after_ts > before_ts then
    insert into result values (7, '7. stage change re-stamps stage_changed_at (correct)');
  else
    insert into result values (7, '7. stage_changed_at not re-stamped (WRONG)');
  end if;

  -- 8. ...and only a stage change does, or "how long has this sat here" resets
  --    every time somebody corrects a phone number.
  update lead set stage_changed_at = now() - interval '10 days' where id = lid;
  select stage_changed_at into before_ts from lead where id = lid;
  update lead set next_action = 'call them' where id = lid;
  select stage_changed_at into after_ts from lead where id = lid;
  if after_ts = before_ts then
    insert into result values (8, '8. non-stage edit leaves stage_changed_at alone (correct)');
  else
    insert into result values (8, '8. non-stage edit re-stamped stage_changed_at (WRONG)');
  end if;

  -- 9. Suppression FLAGS at intake, never rejects. Discarding an inbound lead
  --    because a stale suppression matched is unrecoverable; a flagged row is
  --    visible and reversible.
  insert into suppression (scope, value, reason) values ('email', 'blocked@example.com', '__test fixture__');
  insert into lead (source, company_name, email)
    values ('inbound_form', '__t Suppressed', 'blocked@example.com');
  if exists (select 1 from lead where company_name = '__t Suppressed' and suppressed_at is not null) then
    insert into result values (9, '9. suppressed lead written and flagged, not rejected (correct)');
  else
    insert into result values (9, '9. suppression did not flag the lead (WRONG)');
  end if;

  -- 10. ...and says so on its own timeline.
  if exists (select 1 from lead_activity a join lead l2 on l2.id = a.lead_id
              where l2.company_name = '__t Suppressed'
                and a.metadata->>'event' = 'suppressed') then
    insert into result values (10, '10. suppression recorded on the timeline (correct)');
  else
    insert into result values (10, '10. suppression absent from the timeline (WRONG)');
  end if;

  -- 11. One prospect resolves to at most one lead, so Phase 3's composite FK
  --     can decide outbound-vs-not without ambiguity.
  if outbound_p is not null then
    insert into lead (source, company_name, prospect_id) values ('outbound_scan', '__t P1', outbound_p);
    begin
      insert into lead (source, company_name, prospect_id) values ('referral', '__t P2', outbound_p);
      insert into result values (11, '11. a second lead for one prospect accepted (WRONG)');
    exception when unique_violation then
      insert into result values (11, '11. a second lead for one prospect rejected (correct)');
    end;
  end if;

  -- 12. touch_id is only meaningful on commentary about a touch.
  begin
    insert into lead_activity (lead_id, kind, body, touch_id) values (lid, 'note', 'x', 1);
    insert into result values (12, '12. touch_id accepted on a plain note (WRONG)');
  exception when check_violation then
    insert into result values (12, '12. touch_id rejected on a plain note (correct)');
  end;

  delete from lead where company_name like '__t %';
  delete from suppression where value = 'blocked@example.com';
end $$;

-- ===========================================================================
-- B. Access model — anon and authenticated must reach nothing
-- ===========================================================================
do $$
declare n int;
begin
  set local role authenticated;
  set local request.jwt.claims = '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

  begin
    select count(*) into n from lead;
    insert into result values (13, format('13. authenticated reads lead -> %s rows (WRONG, should be denied)', n));
  exception when insufficient_privilege then
    insert into result values (13, '13. authenticated cannot read lead (correct)');
  end;

  begin
    insert into lead (source, company_name) values ('manual', '__t Sneak');
    insert into result values (14, '14. authenticated created a lead (WRONG)');
  exception when insufficient_privilege then
    insert into result values (14, '14. authenticated cannot create a lead (correct)');
  end;

  -- The views are the back door worth checking: a Postgres view runs with its
  -- OWNER's privileges unless security_invoker is set, so an unguarded view
  -- re-opens exactly what the revoked grants just closed.
  begin
    select count(*) into n from lead_inbox;
    insert into result values (15, format('15. authenticated reads lead_inbox -> %s rows (WRONG)', n));
  exception when insufficient_privilege then
    insert into result values (15, '15. authenticated cannot read lead_inbox (correct)');
  end;

  -- TRUNCATE ignores row-level security entirely; only the grant can stop it.
  begin
    execute 'truncate lead cascade';
    insert into result values (16, '16. authenticated truncated lead (WRONG)');
  exception when insufficient_privilege then
    insert into result values (16, '16. authenticated cannot truncate lead (correct)');
  end;

  reset role;
end $$;

do $$
declare n int;
begin
  set local role anon;
  begin
    select count(*) into n from lead;
    insert into result values (17, format('17. anon reads lead -> %s rows (WRONG)', n));
  exception when insufficient_privilege then
    insert into result values (17, '17. anon cannot read lead (correct)');
  end;
  reset role;
end $$;

select n, note from result order by n;
