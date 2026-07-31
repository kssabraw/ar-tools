-- Read API for the suite.
--
-- The outreach pipeline is an AR Tools MODULE: the database stays in this project, the API and
-- UI live in platform-api and the suite SPA (HANDOFF §2). platform-api holds the service role and
-- is the only client — nothing here is reachable by anon or authenticated, matching the
-- service-role-only posture of the CRM tables.
--
-- Two objects, both read-only:
--
--   v_prospect_status        per-prospect filter verdict, so the suite can list "survived" or
--                            "excluded" without pulling filter_result into Python.
--   outreach_market_summary  the funnel, per-rule counts and spend for one market, aggregated in
--                            Postgres.
--
-- Aggregating in SQL rather than the application is a storage-spec §9 requirement, and it also
-- sidesteps ISSUES I-036 by construction: nothing here can be silently truncated at 1000 rows
-- because no unbounded row set ever crosses the wire.

-- ---------------------------------------------------------------------------
-- v_prospect_status
--
-- `excluded` is derived the same way services/filters.py derives it — any FAILING rule that is
-- not in NON_EXCLUSIONARY_RULES. Franchise matches flag, never exclude (DECISIONS.md), and that
-- is a decision, not an implementation detail, so it is spelled out below rather than inferred.
--
-- DRIFT GUARD: the 'not_franchise' literal below duplicates
-- api/services/filters.NON_EXCLUSIONARY_RULES. api/tests/test_read_api_sql.py asserts the two
-- agree; if a rule is ever added to that frozenset, that test fails until this view is updated.
-- Without the guard, a new non-exclusionary rule would start excluding prospects here while the
-- pipeline kept flagging them, and the two would disagree in silence.
--
-- security_invoker so the view carries the caller's privileges rather than the owner's — a
-- definer-semantics view over RLS-enabled tables is what Supabase's advisor flags as
-- `security_definer_view`, and there is no reason to want it here.
create view v_prospect_status
with (security_invoker = true) as
select
  p.id,
  p.market_id,
  p.submarket_id,
  sm.name              as submarket_name,
  p.place_id,
  p.name,
  p.category,
  p.address,
  p.phone,
  p.website,
  p.rating,
  p.review_count,
  p.lat,
  p.lng,
  p.business_status,
  p.franchise_status,
  p.ingested_at,
  f.evaluated,
  coalesce(f.excluded, false)                    as excluded,
  coalesce(f.rules_failed, array[]::text[])      as rules_failed
from prospect p
left join submarket sm on sm.id = p.submarket_id
left join lateral (
  select
    count(*) > 0                                                   as evaluated,
    coalesce(bool_or(not fr.passed and fr.rule <> 'not_franchise'), false) as excluded,
    array_remove(array_agg(case when not fr.passed then fr.rule end order by fr.rule), null)
                                                                   as rules_failed
  from filter_result fr
  where fr.prospect_id = p.id
) f on true;

comment on view v_prospect_status is
  'Per-prospect filter verdict. excluded = any failing rule outside NON_EXCLUSIONARY_RULES; '
  'evaluated = the filter has run for this prospect at all. Read by platform-api.';

-- ---------------------------------------------------------------------------
-- outreach_market_summary
--
-- One round trip for the whole funnel. Deliberately reports THREE per-rule numbers, not two:
--
--   passed / failed  — the obvious pair
--   not_evaluated    — rows written with passed = true and observed_value = 'not_evaluated'
--
-- The third exists because of ISSUES I-016. filter_result.passed is `not null boolean`, so a
-- disabled rule (review_recency, deferred to Phase 5) has no honest way to say "did not run"
-- except through observed_value. Folding those into `passed` would report 1,388 businesses as
-- having recent reviews when not one of them was checked — a confident, specific, wrong number.
create function outreach_market_summary(p_market_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with prospects as (
    select excluded, evaluated, franchise_status
    from v_prospect_status
    where market_id = p_market_id
  ),
  rules as (
    select
      fr.rule,
      count(*) filter (where fr.passed and fr.observed_value is distinct from 'not_evaluated')
        as passed,
      count(*) filter (where not fr.passed)                        as failed,
      count(*) filter (where fr.observed_value = 'not_evaluated')  as not_evaluated
    from filter_result fr
    join prospect p on p.id = fr.prospect_id
    where p.market_id = p_market_id
    group by fr.rule
  ),
  spend as (
    select stage, provider,
           sum(units)::bigint      as units,
           sum(cost_cents)::bigint as cost_cents
    from cost_ledger
    where market_id = p_market_id
    group by stage, provider
  )
  select jsonb_build_object(
    'market', (
      select to_jsonb(m) from market m where m.id = p_market_id
    ),
    'submarket_count', (select count(*) from submarket where market_id = p_market_id),
    'keyword_count',   (select count(*) from keyword   where market_id = p_market_id),
    'prospects', jsonb_build_object(
      'total',             (select count(*) from prospects),
      'evaluated',         (select count(*) from prospects where evaluated),
      'not_evaluated',     (select count(*) from prospects where not evaluated),
      'survived',          (select count(*) from prospects where evaluated and not excluded),
      'excluded',          (select count(*) from prospects where excluded),
      'flagged_franchise', (select count(*) from prospects where franchise_status = 'flagged')
    ),
    'rules', coalesce(
      (select jsonb_agg(jsonb_build_object(
                'rule', rule, 'passed', passed,
                'failed', failed, 'not_evaluated', not_evaluated) order by rule)
       from rules), '[]'::jsonb),
    'cost', jsonb_build_object(
      'total_cents', coalesce((select sum(cost_cents) from spend), 0),
      'by_stage', coalesce(
        (select jsonb_agg(jsonb_build_object(
                  'stage', stage, 'provider', provider,
                  'units', units, 'cost_cents', cost_cents) order by stage, provider)
         from spend), '[]'::jsonb)
    )
  );
$$;

comment on function outreach_market_summary(uuid) is
  'Funnel, per-rule counts and spend for one market, aggregated in Postgres (storage spec §9). '
  'per-rule not_evaluated is reported separately from passed — see ISSUES I-016.';

-- ---------------------------------------------------------------------------
-- Access: service role only.
--
-- Supabase grants ALL on new objects in `public` to anon/authenticated by default, so these two
-- must be revoked explicitly. PR #534 found the same default silently defeating an append-only
-- grant on the CRM tables; the lesson is that a grant statement here would be additive noise and
-- a revoke is the only thing that changes anything.
revoke all on v_prospect_status from anon, authenticated;
revoke all on function outreach_market_summary(uuid) from anon, authenticated, public;
