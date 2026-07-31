-- An inference about the PROVIDER, kept separate from an observation about the business.
--
-- ISSUES I-041. The LA pull returned no review count for 113 of 1,388 listings, and the evidence
-- says most of them are genuinely zero-review businesses rather than dropped data:
--
--   * `review_count = 0` appears ZERO times across all 1,388 prospects, while counts of 1, 2,
--     3-5 and 6-9 appear 118 / 70 / 129 / 116 times. A provider that reports down to 1 but never
--     emits 0 is encoding zero as null.
--   * 105 of the 113 have a null RATING too, and a rating is an average of reviews — zero reviews
--     mechanically cannot produce one, so null+null is internally coherent.
--   * The remaining 8 carry a numeric rating with a null count, which cannot both be true. Those
--     are provider gaps and stay NULL (one, Mejia Rooter, was confirmed at 3 reviews and now
--     fails the >= 10 rule).
--
-- WHY A FLAG RATHER THAN WRITING 0 INTO review_count.
--
-- "This provider encodes no-reviews as null" is a claim about a vendor convention, not a
-- measurement of any particular business. Writing 0 would launder the two into the same column
-- and make them indistinguishable afterwards: a later pull that returned a real 0, a genuine
-- zero-review listing, and an inference we made on a Tuesday would all read identically, and
-- withdrawing the inference would mean working out which zeroes had been ours. Keeping it in its
-- own field means the claim is visible in every query that touches it and is withdrawn by
-- clearing a boolean.
--
-- `review_count` therefore stays NULL on these rows FOREVER. The filter reads the flag
-- (`filters.evaluate(..., inferred_zero=)`), not a substituted value.
--
-- NOT SET BY THIS MIGRATION. The column ships empty and the flag is applied only after ground
-- truth from an INDEPENDENT source. Re-asking Outscraper cannot settle it — if its parser drops
-- the review block, it drops it again, and the answer comes back null either way. That is the
-- test's whole difficulty: the ambiguous value is also the expected value.

alter table prospect
  add column if not exists review_count_inferred_zero boolean not null default false;

comment on column prospect.review_count_inferred_zero is
  'True when review_count is NULL and the provider''s null is being READ AS ZERO. An inference '
  'about a vendor convention (ISSUES I-041), never a measurement — review_count stays NULL. '
  'Withdraw by clearing the flag; do not write 0.';

-- The flag is only ever meaningful on a row with no count. A real count and an inferred zero
-- cannot both be true, and a constraint says so rather than a comment hoping someone reads it.
alter table prospect drop constraint if exists inferred_zero_requires_null_count;
alter table prospect add constraint inferred_zero_requires_null_count
  check (not review_count_inferred_zero or review_count is null);

-- Serves "which prospects are surviving on an inference rather than a measurement" — the query
-- worth running before any spend is committed against this market.
create index if not exists prospect_inferred_zero_idx
  on prospect (market_id) where review_count_inferred_zero;
