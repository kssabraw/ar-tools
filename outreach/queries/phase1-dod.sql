-- Phase 1 definition of done (docs/PHASE-1-BRIEF.md §6).
-- Four questions, answerable from SQL alone. Set :market_id before running.
--
-- Note on "survived": a prospect survives when it failed no EXCLUSIONARY rule. `not_franchise`
-- is excluded from that test because a franchise match flags for review and never excludes.


-- 1. How many listings were pulled, and what it cost. ---------------------------------------
--
-- `units` on the ingest row is rows RETURNED by the provider, before dedup — that is what was
-- billed. `prospect` is the post-dedup count. The gap between them is the tile overlap, and a
-- gap near zero means the tiling is too sparse to be treating this as full market coverage.
--
-- cost_cents is units x the configured rate, NOT a provider-reported figure — the API does not
-- return one. Reconcile against the Outscraper dashboard by hand once per cycle (ISSUES I-022).

select
  (select count(*) from prospect where market_id = :market_id)              as prospects_after_dedup,
  coalesce(sum(l.units)    filter (where l.stage = 'a1_ingest'), 0)         as rows_returned_billed,
  coalesce(sum(l.cost_cents), 0)                                            as total_cost_cents,
  round(coalesce(sum(l.cost_cents), 0) / 100.0, 2)                          as total_cost_dollars
from cost_ledger l
where l.market_id = :market_id;


-- Cost broken out per stage per provider.
select stage, provider, sum(units) as units, sum(cost_cents) as cost_cents
from cost_ledger
where market_id = :market_id
group by stage, provider
order by cost_cents desc, stage;


-- 2a. How many survived. --------------------------------------------------------------------

select
  count(*) filter (where not p.excluded)                as survived,
  count(*) filter (where p.excluded)                    as excluded,
  count(*) filter (where p.franchise_status = 'flagged') as flagged_franchise,
  count(*)                                              as total
from (
  select
    pr.id,
    pr.franchise_status,
    exists (
      select 1 from filter_result fr
      where fr.prospect_id = pr.id and not fr.passed and fr.rule <> 'not_franchise'
    ) as excluded
  from prospect pr
  where pr.market_id = :market_id
) p;


-- 2b. How many failed each rule. -------------------------------------------------------------
--
-- These sum to MORE than the excluded count, by design: every rule is evaluated for every
-- prospect, so a dead listing appears under each gate it failed. `not_evaluated` counts rules
-- that were disabled or had no data, which is why a rule can show zero failures and still not be
-- doing nothing.

select
  fr.rule,
  count(*) filter (where not fr.passed)                                  as failed,
  count(*) filter (where fr.passed and fr.observed_value = 'not_evaluated') as not_evaluated,
  count(*) filter (where fr.passed and fr.observed_value is distinct from 'not_evaluated') as passed,
  count(*)                                                               as evaluated_rows
from filter_result fr
join prospect pr on pr.id = fr.prospect_id
where pr.market_id = :market_id
group by fr.rule
order by failed desc, fr.rule;


-- 3. For any excluded business, which rules it failed. ---------------------------------------
--
-- The full list per business, not the first match.

select
  pr.name,
  pr.place_id,
  pr.business_status,
  pr.review_count,
  string_agg(fr.rule || coalesce(' (' || fr.observed_value || ')', ''), ', ' order by fr.rule)
    as failed_rules
from prospect pr
join filter_result fr on fr.prospect_id = pr.id and not fr.passed
where pr.market_id = :market_id
group by pr.id, pr.name, pr.place_id, pr.business_status, pr.review_count
order by count(fr.rule) desc, pr.name;


-- One named business, for spot checks.
select fr.rule, fr.passed, fr.observed_value, fr.evaluated_at
from filter_result fr
join prospect pr on pr.id = fr.prospect_id
where pr.place_id = :place_id
order by fr.rule;


-- 4. Which businesses are flagged as possible franchises and await review. -------------------
--
-- These are IN the pipeline, not excluded from it. They must not be contacted until a human has
-- reviewed them — nothing in Phase 1 contacts anyone, so the flag is the whole mechanism today.

select
  pr.name,
  pr.place_id,
  pr.phone,
  pr.website,
  pr.review_count,
  fr.observed_value as matched_pattern
from prospect pr
join filter_result fr
  on fr.prospect_id = pr.id and fr.rule = 'not_franchise' and not fr.passed
where pr.market_id = :market_id
  and pr.franchise_status = 'flagged'
order by pr.review_count desc nulls last, pr.name;


-- Surviving prospects, ordered by review count.
--
-- Review count is an INSPECTION ORDER ONLY — the brief's suggestion for when an order is needed.
-- It is not a score, not a proxy for one, and prospect_score is not written in this phase.

select pr.name, pr.review_count, pr.rating, pr.phone, pr.website, pr.franchise_status
from prospect pr
where pr.market_id = :market_id
  and not exists (
    select 1 from filter_result fr
    where fr.prospect_id = pr.id and not fr.passed and fr.rule <> 'not_franchise'
  )
order by pr.review_count desc nulls last;
