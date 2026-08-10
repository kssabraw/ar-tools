-- Category relevance — the three-bucket gate (keep / review / drop).
--
-- A Google Maps category search returns adjacent trades, not only the searched one. A live
-- "plumbing contractor" pull for Inglewood surfaced apartment buildings, tool stores, HVAC firms,
-- painters and plumbing-SUPPLY warehouses — ~half of the contactable set — because none of the six
-- Phase-1 filter rules ask whether a listing is actually the trade. `filters.evaluate` now runs a
-- seventh rule keyed on Google's own PRIMARY category; this column records where each prospect
-- landed so the review pile and the drops are queryable, and so a HUMAN ruling survives re-filter.
--
--   relevant           primary category is on the vertical's allow-list          -> contactable
--   review             primary is off-list but a SECONDARY category matches      -> human glances
--   off_category       primary off-list, no secondary match                      -> excluded
--   unknown            rule disabled / vertical unconfigured / no category        -> kept (default)
--   confirmed_relevant a human overruled the match toward keep                    -> protected
--   confirmed_off      a human overruled the match toward drop                    -> protected
--
-- The computed values ('relevant'/'review'/'off_category'/'unknown') are re-derived on every
-- filter run. The 'confirmed_*' values are human decisions and belong to the same class as a
-- verified review count or a confirmed franchise ruling — re-derivable code must never revert them,
-- so they are protected in the database (below), not only at the call site (I-053/I-054).

alter table prospect
  add column if not exists category_status text not null default 'unknown';

alter table prospect drop constraint if exists prospect_category_status_known;
alter table prospect add constraint prospect_category_status_known
  check (category_status in (
    'unknown', 'relevant', 'review', 'off_category', 'confirmed_relevant', 'confirmed_off'
  ));

comment on column prospect.category_status is
  'Which relevance bucket the category gate placed this prospect in. ''confirmed_*'' are human '
  'rulings, protected from re-derivation by prospect_preserve_decisions().';

-- ---------------------------------------------------------------------------
-- Extend the human-decision guard (migration 20260801140000) with a fourth clause.
--
-- Reproduced in full because a function is replaced wholesale, not patched. Clauses 1–3 are
-- unchanged; clause 4 protects a confirmed category ruling exactly as clause 2 protects a
-- confirmed franchise ruling — `run_filter` writes the computed bucket unconditionally, and a
-- reviewer who recorded confirmed_relevant/confirmed_off must not have it undone by the next run.
-- ---------------------------------------------------------------------------
create or replace function public.prospect_preserve_decisions()
returns trigger
language plpgsql
security definer
set search_path = public
as $function$
begin
  -- 1. A verified review count outranks the provider payload.
  if old.review_count_source is distinct from 'provider'
     and new.review_count_source is not distinct from old.review_count_source
     and new.review_count is distinct from old.review_count then
    new.review_count := old.review_count;
  end if;

  -- 2. A human franchise ruling outranks the name-pattern match.
  if old.franchise_status in ('confirmed_franchise', 'confirmed_independent')
     and new.franchise_status = 'flagged' then
    new.franchise_status := old.franchise_status;
  end if;

  -- 3. The inferred-zero flag is not re-derivable at all.
  if old.review_count_inferred_zero and not new.review_count_inferred_zero
     and new.review_count is null then
    new.review_count_inferred_zero := old.review_count_inferred_zero;
  end if;

  -- 4. A human category ruling outranks the category match.
  --
  -- `run_filter` writes the computed bucket ('relevant'/'review'/'off_category'/'unknown') on every
  -- run. A reviewer who confirmed a listing IS the trade (confirmed_relevant) or is NOT
  -- (confirmed_off) — both stronger statements than any computed bucket — must not have that reset
  -- by the next routine re-filter. Symmetric with clause 2.
  if old.category_status in ('confirmed_relevant', 'confirmed_off')
     and new.category_status not in ('confirmed_relevant', 'confirmed_off') then
    new.category_status := old.category_status;
  end if;

  return new;
end;
$function$;

-- The trigger already binds this function by name (20260801140000); replacing the function is
-- enough. Recreated defensively so this migration is self-contained if applied to a fresh DB.
drop trigger if exists prospect_preserve_decisions on prospect;
create trigger prospect_preserve_decisions
  before update on prospect
  for each row execute function public.prospect_preserve_decisions();

revoke all on function public.prospect_preserve_decisions() from anon, authenticated, public;

-- "Which businesses are in the review pile" — the human-glance queue.
create index if not exists prospect_category_review_idx
  on prospect (market_id) where category_status = 'review';
