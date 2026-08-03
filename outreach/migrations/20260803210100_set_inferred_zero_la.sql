-- Apply `review_count_inferred_zero` to the 105. ISSUES I-066; owner decision, 2026-08-03.
--
-- `20260801130000` shipped this column deliberately unset, with one condition on setting it:
-- "applied only after ground truth from an INDEPENDENT source". That condition is now met, and
-- this migration is the act it was waiting for.
--
-- THE EVIDENCE, in the order it actually constrains the conclusion:
--
--   * MECHANICAL. A rating is an average of reviews. Zero reviews cannot produce one. All 105 of
--     these rows have a null rating AND a null count, which is the only internally coherent
--     shape for a zero-review listing. (The 7 rows carrying a rating with no count are NOT
--     touched — those two facts cannot both be true, so they are provider gaps, not zeroes.)
--   * DISTRIBUTIONAL. `review_count = 0` appears zero times in all 1,388 prospects, while 1, 2,
--     3-5 and 6-9 appear 118 / 70 / 129 / 116 times. A provider that reports down to 1 and never
--     emits 0 is encoding zero as null.
--   * CORROBORATED. An independent vendor was asked (I-061, I-066). DataForSEO returned no count
--     for 20 of 20 sampled, with no timeouts — and the control group proved the same call
--     resolves down to a single review (Maximum Plumbing, votes_count 1). Two vendors decline to
--     report a count for these listings, and the instrument is known to work.
--
-- WHY NOW RATHER THAN ON MORE EVIDENCE. No source will ever affirmatively report zero — that is
-- the vendor convention under test, so waiting for an explicit 0 means waiting forever, and an
-- inference held open indefinitely is not caution, it is a decision never made. The flag exists
-- precisely so this can be visible and reversible rather than certain.
--
-- WHAT IS NOT BEING CLAIMED. `review_count` stays NULL on every one of these rows. Nothing here
-- measures any business; this records that we are READING the provider's null as zero. The
-- companion migration `20260803210000` installs the trigger that records any future real count
-- landing on these rows, so the inference is falsifiable rather than merely asserted.

do $$
declare
  target_count integer;
  updated_count integer;
begin
  select count(*) into target_count
  from prospect
  where review_count is null and rating is null and not review_count_inferred_zero;

  -- The set this decision was made about was 105 rows. If it is not 105, the data has moved since
  -- the decision — a re-ingest, a correction like Mejia Rooter's (I-053), a second market — and
  -- the right response is to stop and re-derive the decision, not to flag whatever is there now.
  -- A human decision must not silently widen its own scope.
  if target_count <> 105 then
    raise exception
      'expected 105 rows with null count and null rating, found % — the set has changed since the I-066 decision; re-derive before applying',
      target_count;
  end if;

  update prospect
     set review_count_inferred_zero = true
   where review_count is null
     and rating is null
     and not review_count_inferred_zero;

  get diagnostics updated_count = row_count;
  raise notice 'review_count_inferred_zero set on % prospects (I-066)', updated_count;
end $$;
