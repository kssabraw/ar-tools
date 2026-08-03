-- The audit that makes the inferred-zero flag falsifiable.
--
-- ISSUES I-066. `review_count_inferred_zero` is about to be set on 105 LA prospects: an inference
-- that the provider encodes "no reviews" as null, corroborated by two independent vendors but
-- never affirmatively stated by either. An inference that cannot be caught being wrong is just an
-- assertion, so this is the mechanism that catches it.
--
-- The geo-grid scan will eventually return `rating.votes_count` for these same listings from real
-- scan data. That is the first source that can CONTRADICT the flag — and the moment it does is
-- exactly the moment the contradiction is easiest to lose, because the natural thing for a
-- backfill to do is write the count and move on.
--
-- WHY A TRIGGER RATHER THAN A RULE IN THE BACKFILL.
--
-- The backfill does not exist yet (Phase 2 scanning has not started). A convention written down
-- now, for code written later, by someone who may not read this file, is precisely the kind of
-- protection that this repo has twice watched fail — HANDOFF §6.1 documented the redeploy trap
-- and it was not read first (I-063), and the paid-run procedure was followed and still misfired
-- (I-064). So the audit lives where no write path can skip it, in the same spirit as the
-- suppression trigger: structural, not procedural.
--
-- The `inferred_zero_requires_null_count` CHECK already makes flag+count mutually exclusive, so a
-- backfill writing a real count onto a flagged row would ERROR. That is loud, but it is the wrong
-- kind of loud: it aborts the backfill rather than recording what was learned. This trigger
-- resolves the row instead — records the disagreement, clears the flag, lets the measurement land
-- — so the count wins (a measurement always beats an inference) and the inference's failure is
-- preserved rather than the transaction.

create table if not exists review_inferred_zero_audit (
  id             bigint generated always as identity primary key,
  prospect_id    uuid not null references prospect(id) on delete cascade,
  place_id       text not null,
  market_id      uuid not null,
  prospect_name  text not null,
  observed_count integer not null,
  observed_rating numeric,
  -- 'contradicted' — a real count arrived on a row we had inferred to be zero. The inference was
  --                  wrong for this listing.
  -- 'confirmed'    — a real count of 0 arrived. No vendor has ever emitted one, so this would
  --                  itself be news; it is spelled out so the two never collapse into one row
  --                  type if some future source does report zero.
  verdict        text not null check (verdict in ('contradicted', 'confirmed')),
  observed_at    timestamptz not null default now()
);

comment on table review_inferred_zero_audit is
  'Every time a real review count landed on a row carrying review_count_inferred_zero. This is '
  'the falsification record for the I-066 inference: a non-empty table with verdict=contradicted '
  'means the vendor-convention claim is wrong for those listings, and a large one means it should '
  'be withdrawn wholesale. Written only by the prospect_audit_inferred_zero trigger.';

create index if not exists review_inferred_zero_audit_verdict_idx
  on review_inferred_zero_audit (verdict, observed_at desc);

create or replace function public.prospect_audit_inferred_zero()
returns trigger
language plpgsql
security definer
set search_path = public
as $function$
begin
  -- Only the transition that matters: a flagged row acquiring a real count.
  if old.review_count_inferred_zero and new.review_count is not null then
    insert into review_inferred_zero_audit (
      prospect_id, place_id, market_id, prospect_name,
      observed_count, observed_rating, verdict
    )
    values (
      old.id, old.place_id, old.market_id, old.name,
      new.review_count, new.rating,
      case when new.review_count = 0 then 'confirmed' else 'contradicted' end
    );

    -- Loud in the server log as well as the table. The table is the durable record; this is what
    -- a human tailing a backfill actually sees.
    raise warning
      'inferred-zero % : % (place_id %) was flagged zero-by-inference and measured at % reviews',
      case when new.review_count = 0 then 'CONFIRMED' else 'CONTRADICTED' end,
      old.name, old.place_id, new.review_count;

    -- Let the measurement land. Clearing the flag here is what keeps the CHECK constraint
    -- satisfied without the backfill needing to know the flag exists — and the cleared flag is
    -- not a silent loss, because the row above records that it was cleared and why.
    new.review_count_inferred_zero := false;
  end if;

  return new;
end;
$function$;

-- Name matters: BEFORE UPDATE triggers fire in alphabetical order, and this must run before
-- `prospect_preserve_decisions`, whose flag-preservation branch is guarded on
-- `new.review_count is null` and therefore correctly declines to re-set a flag this trigger has
-- cleared alongside a real count. 'a' sorts before 'p'; that is load-bearing, not incidental.
drop trigger if exists prospect_audit_inferred_zero on prospect;
create trigger prospect_audit_inferred_zero
  before update on prospect
  for each row execute function public.prospect_audit_inferred_zero();

revoke all on function public.prospect_audit_inferred_zero() from anon, authenticated, public;
