-- Human decisions must survive re-derivation. Enforced in the database, not at call sites.
--
-- THE CLASS, not the instance. Three occurrences of one pattern have now been found:
--
--   I-035  a run diagnosed from a lagging log stream instead of the durable record
--   I-036  a read silently truncated, so a derived count was confidently wrong
--   I-053  a verified review count ignored because the filter re-parses from raw
--
-- The shape is always the same: a decision is stored in a column, and some later code path
-- re-derives that value from source and overwrites or ignores it. Nothing errors. The revert is
-- found weeks later by someone asking why a number moved.
--
-- Fixing the third instance in `run_filter` did not close it. The ingest upsert
-- (`on_conflict = place_id`) rewrites `review_count` from the provider payload on every re-ingest,
-- so the same correction had a SECOND revert path that a call-site fix would have missed — which
-- is exactly the argument for guarding the class rather than the case.
--
-- A trigger holds regardless of which code path writes: the ingest, the filter, a future backfill,
-- a hand-written UPDATE at 2am. That is the same reasoning that makes `lead_log_changes` a trigger
-- rather than an application concern.

-- ---------------------------------------------------------------------------
-- Provenance for review_count
--
-- Without this the database cannot tell a provider value from a corrected one — they are both
-- just integers — and "preserve the human decision" has nothing to key on.
--   provider  written from the Outscraper payload; freely overwritten by a re-ingest
--   verified  established outside the provider (manual check, single-place lookup)
--   geogrid   recovered from a DataForSEO Maps response (I-045). Also not the provider's listing
--             payload, so it outranks it for the same reason.
-- ---------------------------------------------------------------------------
alter table prospect
  add column if not exists review_count_source text not null default 'provider';

alter table prospect drop constraint if exists review_count_source_known;
alter table prospect add constraint review_count_source_known
  check (review_count_source in ('provider', 'verified', 'geogrid'));

comment on column prospect.review_count_source is
  'Where review_count came from. Anything other than ''provider'' is protected from re-ingest by '
  'prospect_preserve_decisions() — see ISSUES I-053/I-054.';

-- ---------------------------------------------------------------------------
-- The guard
--
-- Deliberately narrow: it protects three specific columns whose values can encode a human ruling,
-- and touches nothing else. A broad "never overwrite anything" trigger would be unpredictable and
-- would eventually be worked around, which is worse than no guard.
-- ---------------------------------------------------------------------------
create or replace function public.prospect_preserve_decisions()
returns trigger
language plpgsql
security definer
set search_path = public
as $function$
begin
  -- 1. A verified review count outranks the provider payload.
  --
  -- The ingest upsert writes review_count from raw on every re-ingest and does not set
  -- review_count_source, so an UPDATE through it arrives with the OLD source still attached.
  -- That is what makes this checkable: a write that did not explicitly claim better provenance
  -- cannot overwrite a value that has it.
  if old.review_count_source is distinct from 'provider'
     and new.review_count_source is not distinct from old.review_count_source
     and new.review_count is distinct from old.review_count then
    new.review_count := old.review_count;
  end if;

  -- 2. A human franchise ruling outranks the name-pattern match.
  --
  -- `run_filter` updates matched prospects to 'flagged' unconditionally. A reviewer who has
  -- looked at a listing and recorded confirmed_independent — or confirmed_franchise, which is a
  -- STRONGER statement than flagged and would also be downgraded — must not have that undone by
  -- the next routine filter run. The pattern list is an unvalidated seed (I-020); a human who
  -- read the listing is better evidence than a substring match, in both directions.
  if old.franchise_status in ('confirmed_franchise', 'confirmed_independent')
     and new.franchise_status = 'flagged' then
    new.franchise_status := old.franchise_status;
  end if;

  -- 3. The inferred-zero flag is not re-derivable at all.
  --
  -- It records a judgement about a provider convention (I-051) and nothing in the payload implies
  -- it. It is not currently written by any pipeline path, so this is a guard against a future one
  -- rather than an observed bug — which is the point of auditing the class instead of the case.
  if old.review_count_inferred_zero and not new.review_count_inferred_zero
     and new.review_count is null then
    new.review_count_inferred_zero := old.review_count_inferred_zero;
  end if;

  return new;
end;
$function$;

drop trigger if exists prospect_preserve_decisions on prospect;
create trigger prospect_preserve_decisions
  before update on prospect
  for each row execute function public.prospect_preserve_decisions();

revoke all on function public.prospect_preserve_decisions() from anon, authenticated, public;

-- ---------------------------------------------------------------------------
-- Mejia Rooter: the correction that prompted all of this.
--
-- Confirmed at 3 Google reviews against a stored rating of exactly 5.0, which the provider
-- returned with a null count. Marking the provenance is what puts it behind the guard above.
-- ---------------------------------------------------------------------------
update prospect
   set review_count_source = 'verified'
 where place_id = 'ChIJx0kGqs3GwoARp_f3ye-NqfY'
   and review_count = 3;

-- `submarket_id` is deliberately NOT guarded. It is recomputed by nearest-centroid on every
-- re-ingest, but that computation is deterministic and depends only on geometry, which is
-- immutable once a submarket is scanned (DECISIONS.md) — so a re-ingest reproduces the same
-- value rather than reverting anything. It becomes a member of this class the moment a human can
-- reassign a prospect by hand, and there is no such path today. Recorded in ISSUES I-054 so the
-- absence is a decision rather than an oversight.
