"""Tests for the I-041 review-count verifier.

The classifier is where the money lands: it decides whether a lookup counts as evidence that a
null means zero. Getting it wrong in the permissive direction would encode a false convention
into every future market pull, so the tests below lean on the cases where the count field is
absent and the sub-objects have to carry the verdict.

No network and no database — the classifier is pure and takes a provider dict.
"""

import pytest

from api.services.review_verify import (
    AMBIGUOUS,
    ERROR,
    HAS_REVIEWS,
    ZERO,
    LookupResult,
    VerifyReport,
    classify_lookup,
    select_candidates,
)


# --- classify_lookup ---------------------------------------------------------------------


def test_a_returned_count_settles_it():
    r = classify_lookup({"place_id": "p", "name": "n", "reviews": 7, "rating": 4.5})
    assert r.verdict == HAS_REVIEWS
    assert r.review_count == 7


def test_an_explicit_zero_is_a_zero():
    """If the provider ever emits 0 outright, that one row answers the convention question — it
    CAN say zero, so a null elsewhere means something else."""
    r = classify_lookup({"place_id": "p", "name": "n", "reviews": 0})
    assert r.verdict == ZERO
    assert r.review_count == 0


def test_a_star_histogram_beats_a_missing_count():
    """`reviews_per_score` cannot exist without reviews. This is the case the whole exercise turns
    on: the count is null and the listing demonstrably has reviews anyway."""
    r = classify_lookup(
        {"place_id": "p", "name": "n", "reviews": None, "reviews_per_score": {"5": 3, "4": 1}}
    )
    assert r.verdict == HAS_REVIEWS
    assert r.has_histogram


def test_an_all_zero_histogram_is_not_evidence_of_reviews():
    """A histogram of zeroes is a rendered empty widget, not four reviews."""
    r = classify_lookup(
        {"place_id": "p", "name": "n", "reviews": None,
         "reviews_per_score": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}}
    )
    assert r.verdict == ZERO
    assert not r.has_histogram


def test_inline_review_text_beats_a_missing_count():
    r = classify_lookup(
        {"place_id": "p", "name": "n", "reviews": None,
         "reviews_data": [{"review_text": "great"}, {"review_text": "fine"}]}
    )
    assert r.verdict == HAS_REVIEWS
    assert r.inline_reviews == 2


def test_a_rating_with_no_count_is_a_dropped_count_not_a_zero():
    """The 8-group shape. A rating is an average, so it cannot be an average of nothing — this is
    exactly the Mejia Rooter case, which turned out to have 3 real reviews."""
    r = classify_lookup({"place_id": "p", "name": "n", "reviews": None, "rating": 4.6})
    assert r.verdict == HAS_REVIEWS


def test_nothing_at_all_reads_as_zero_but_only_weakly():
    """No count, no rating, no histogram, no inline reviews. Consistent with a true zero — and
    also with a second parse failure, which is why the command reports the split rather than a
    single verdict."""
    r = classify_lookup({"place_id": "p", "name": "n", "reviews": None})
    assert r.verdict == ZERO


def test_an_empty_response_is_an_error_not_a_zero():
    """A lookup that returned nothing tells us nothing. Scoring it as ZERO would let failed
    requests silently argue in favour of the flag."""
    r = classify_lookup(None)
    assert r.verdict == ERROR
    assert r.review_count is None


def test_place_id_falls_back_to_google_id():
    r = classify_lookup({"google_id": "g", "title": "T", "reviews": 4})
    assert r.place_id == "g"
    assert r.name == "T"


def test_a_string_count_is_not_trusted_as_a_number():
    """Type confusion here would turn '0' into a truthy count. Only real numbers are read."""
    r = classify_lookup({"place_id": "p", "name": "n", "reviews": "lots"})
    assert r.review_count is None


# --- recommendation ----------------------------------------------------------------------


def _report(*verdicts, counts=None):
    counts = counts or {}
    rep = VerifyReport(requested=len(verdicts))
    rep.results = [
        LookupResult(place_id=f"p{i}", name="n", verdict=v, review_count=counts.get(i))
        for i, v in enumerate(verdicts)
    ]
    return rep


def test_a_single_contradiction_withholds_the_flag():
    """One listing with reviews is enough to refuse. The flag would be written across every
    future market pull, so one false zero here is a systematic error there."""
    rec = _report(ZERO, ZERO, ZERO, ZERO, HAS_REVIEWS).recommendation()
    assert rec.startswith("DO NOT SET THE FLAG")


def test_a_clean_sweep_supports_the_flag_without_applying_it():
    rec = _report(*[ZERO] * 20).recommendation()
    assert rec.startswith("SUPPORTS THE FLAG")
    assert "human call" in rec


def test_mostly_ambiguous_is_inconclusive_and_names_the_next_step():
    rec = _report(AMBIGUOUS, AMBIGUOUS, AMBIGUOUS, ZERO).recommendation()
    assert "INCONCLUSIVE" in rec
    assert "DataForSEO" in rec


def test_any_error_blocks_a_conclusion():
    """A partly-failed run must not be read as a partial result — the failures are not a random
    sample of the population."""
    rec = _report(ZERO, ZERO, ERROR).recommendation()
    assert "INCONCLUSIVE" in rec


def test_counts_found_reports_the_actual_numbers():
    rep = _report(HAS_REVIEWS, HAS_REVIEWS, ZERO, counts={0: 12, 1: 3})
    assert rep.counts_found == [3, 12]


# --- sampling ----------------------------------------------------------------------------


def test_sample_is_deterministic_and_not_ingestion_ordered():
    """Ordering by ingestion or name would sample one tile or one alphabetic slice. A biased
    sample of a convention question is worse than no sample."""
    rows = [{"place_id": p} for p in ("Cq", "Aq", "Bq", "Zq")]
    picked = [r["place_id"] for r in select_candidates(rows, 3)]
    assert picked == ["Aq", "Bq", "Cq"]
    assert picked == [r["place_id"] for r in select_candidates(list(reversed(rows)), 3)]


def test_sample_never_exceeds_the_limit():
    rows = [{"place_id": f"p{i}"} for i in range(50)]
    assert len(select_candidates(rows, 20)) == 20
    assert len(select_candidates(rows[:5], 20)) == 5
