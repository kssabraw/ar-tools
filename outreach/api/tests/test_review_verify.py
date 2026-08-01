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


def _report(*verdicts, counts=None, group="both_null"):
    counts = counts or {}
    rep = VerifyReport(requested=len(verdicts), group=group)
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


# --- the control group -------------------------------------------------------------------
#
# The first real run came back 16 ambiguous / 4 error: DataForSEO found every listing and
# reported no count for any of them. That is two vendors silent, which reads as evidence — but
# "both providers omit the count when there are no reviews" and "this endpoint does not carry
# counts at all" produce IDENTICAL output, and one of them would have us flag 105 prospects on a
# measurement error. Prospects with a KNOWN count separate the two. The verdicts invert, because
# this group tests the instrument rather than the prospects.


def test_finding_every_known_reviewer_validates_the_instrument():
    rec = _report(*[HAS_REVIEWS] * 5, group="control").recommendation()
    assert rec.startswith("INSTRUMENT VALID")


def test_finding_none_of_them_disqualifies_the_evidence():
    """The outcome that matters most: if the endpoint misses listings that demonstrably have
    reviews, its silence on the 105 means nothing, and no volume of further lookups will fix
    that."""
    rec = _report(*[AMBIGUOUS] * 5, group="control").recommendation()
    assert rec.startswith("INSTRUMENT INVALID")
    assert "do not set the flag" in rec


def test_finding_some_of_them_is_not_good_enough():
    """A provider that reports counts most of the time still cannot have its silence read as a
    zero — the missing ones are exactly the population under test."""
    rec = _report(HAS_REVIEWS, HAS_REVIEWS, AMBIGUOUS, group="control").recommendation()
    assert rec.startswith("INSTRUMENT UNRELIABLE")


def test_a_control_run_that_only_errored_proves_nothing():
    rec = _report(ERROR, ERROR, group="control").recommendation()
    assert "INCONCLUSIVE" in rec


def test_a_control_error_alongside_successes_does_not_block_the_verdict():
    """Unlike the prospect groups, a partial control run is still informative: the lookups that
    DID complete each demonstrate the instrument works."""
    rec = _report(HAS_REVIEWS, HAS_REVIEWS, ERROR, group="control").recommendation()
    assert rec.startswith("INSTRUMENT VALID")


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


# --- DataForSEO: the independent check ---------------------------------------------------
#
# The reason this provider is worth paying for is that it answers the actual question. Outscraper
# is being asked whether its own null means zero, and if the null comes from a parse failure it
# will fail the same way twice (I-050). DataForSEO is queried by place_id and returns the reviews
# themselves — and a reviews_count of 0 is a POSITIVE ASSERTION of zero, which is precisely what
# Outscraper never emits.

from api.services.dataforseo_client import DataForSEOError, PlaceReviews, parse_place_reviews
from api.services.review_verify import classify_dataforseo


def _reviews(count=None, rating=None, items=0):
    return PlaceReviews(place_id="p", reviews_count=count, rating=rating, items_returned=items)


def test_an_explicit_zero_settles_the_convention_question():
    """The single most valuable answer this can return. Outscraper emits 0 for nobody in 1,388
    prospects; a second vendor saying 0 outright is the evidence that null meant zero."""
    r = classify_dataforseo(_reviews(count=0))
    assert r.verdict == ZERO
    assert r.review_count == 0


def test_a_positive_count_refutes_the_convention():
    r = classify_dataforseo(_reviews(count=14, rating=4.6))
    assert r.verdict == HAS_REVIEWS
    assert r.review_count == 14


def test_review_items_beat_a_missing_count():
    """If the count fails to parse but reviews came back, the listing plainly has reviews."""
    r = classify_dataforseo(_reviews(count=None, items=3))
    assert r.verdict == HAS_REVIEWS


def test_both_providers_silent_is_ambiguous_not_zero():
    """The trap. Rounding a second silence down to 'zero' would let absence of evidence argue for
    the conclusion under test — which is the entire error this second vendor exists to avoid."""
    r = classify_dataforseo(_reviews(count=None))
    assert r.verdict == AMBIGUOUS


def test_a_failed_lookup_is_an_error_not_a_zero():
    assert classify_dataforseo(None).verdict == ERROR


# --- response parsing --------------------------------------------------------------------


def _envelope(result, status=20000):
    return {"tasks": [{"status_code": status, "result": result}]}


def test_parses_count_rating_and_items():
    got = parse_place_reviews(
        _envelope([{"place_id": "p", "reviews_count": 42, "rating": {"value": 4.4},
                    "items": [{"review_text": "a"}, {"review_text": "b"}]}]),
        "p",
    )
    assert got.reviews_count == 42
    assert got.rating == 4.4
    assert got.items_returned == 2


def test_count_is_not_the_item_count():
    """`depth` bounds the items returned but never `reviews_count`. Reading the item count as the
    review count would understate every busy business in the market."""
    got = parse_place_reviews(
        _envelope([{"reviews_count": 400, "items": [{"review_text": "x"}] * 10}]), "p"
    )
    assert got.reviews_count == 400
    assert got.items_returned == 10


def test_a_task_level_error_raises_rather_than_reading_as_zero():
    """DataForSEO reports task failures inside a 200. Treating one as 'no reviews' would let an
    outage argue in favour of the flag."""
    try:
        parse_place_reviews(_envelope([], status=40501), "p")
    except DataForSEOError as exc:
        assert "40501" in str(exc)
    else:
        raise AssertionError("a failed task was read as a result")


def test_an_empty_result_block_raises():
    try:
        parse_place_reviews(_envelope([]), "p")
    except DataForSEOError:
        pass
    else:
        raise AssertionError("a missing result block was read as a result")


def test_zero_reviews_with_an_ok_task_is_a_real_zero_not_an_error():
    """The distinction that matters: an OK task reporting reviews_count 0 is data, whereas a
    missing result block is a failure. Collapsing them loses the only definitive answer."""
    got = parse_place_reviews(_envelope([{"reviews_count": 0, "items": []}]), "p")
    assert got.reviews_count == 0
    assert classify_dataforseo(got).verdict == ZERO


# --- my_business_info: the endpoint that actually exists ---------------------------------
#
# `reviews/live` returns 404 against these credentials. The probe found `my_business_info/live`
# and, via its own 40501, named the required field as `keyword` — but not what a *place* looks
# like inside one. So the value form is discovered at runtime and these tests cover the discovery
# as much as the parsing.

from api.services.dataforseo_client import build_lookup_bodies, parse_my_business_info


def _mbi(record, status=20000):
    return {"tasks": [{"status_code": status, "result": [{"items": [record]}]}]}


def test_votes_count_is_the_review_count():
    got = parse_my_business_info(_mbi({"place_id": "p", "rating": {"value": 4.7, "votes_count": 31}}), "p")
    assert got.reviews_count == 31
    assert got.rating == 4.7


def test_zero_votes_is_the_answer_this_whole_exercise_wants():
    """The one result that settles I-041. Outscraper emits 0 for nobody in 1,388 prospects; a
    second vendor asserting 0 outright is what makes the null readable as a zero."""
    got = parse_my_business_info(_mbi({"place_id": "p", "rating": {"value": None, "votes_count": 0}}), "p")
    assert got.reviews_count == 0
    assert classify_dataforseo(got).verdict == ZERO


def test_a_missing_votes_count_is_not_a_zero():
    """Absent and zero are different claims. Reading a parse gap as 'zero reviews' would let this
    verifier vote for the conclusion it exists to test."""
    got = parse_my_business_info(_mbi({"place_id": "p", "rating": {"value": 4.1}}), "p")
    assert got.reviews_count is None
    assert classify_dataforseo(got).verdict == AMBIGUOUS


def test_flat_spellings_are_accepted_as_fallbacks():
    """The envelope is measured from one live sample, not from a contract, so the parser reads
    the likely spellings rather than betting the run on one."""
    assert parse_my_business_info(_mbi({"place_id": "p", "reviews_count": 9}), "p").reviews_count == 9


def test_a_record_without_an_items_wrapper_still_parses():
    body = {"tasks": [{"status_code": 20000, "result": [{"place_id": "p", "rating": {"votes_count": 5}}]}]}
    assert parse_my_business_info(body, "p").reviews_count == 5


def test_a_task_error_raises_so_the_ladder_moves_on():
    with pytest.raises(DataForSEOError):
        parse_my_business_info(_mbi({}, status=40501), "p")


def test_a_different_place_id_is_flagged_not_believed():
    """The name-search rungs can land on a neighbouring business. A true review count for the
    wrong listing is worse than no answer, because it looks exactly like an answer."""
    got = parse_my_business_info(_mbi({"place_id": "OTHER", "rating": {"votes_count": 88}}), "p")
    assert not got.place_id_matches
    assert classify_dataforseo(got).verdict == AMBIGUOUS


def test_a_matching_place_id_is_believed():
    got = parse_my_business_info(_mbi({"place_id": "p", "rating": {"votes_count": 88}}), "p")
    assert got.place_id_matches
    assert classify_dataforseo(got).verdict == HAS_REVIEWS


# --- the keyword ladder ------------------------------------------------------------------


def test_place_id_is_tried_first():
    """Ordered by how much the answer is worth, not by how likely the form is to be accepted —
    the place_id rung is the only one that cannot match the wrong business."""
    forms = build_lookup_bodies("PID", "Acme Plumbing", 34.0, -118.2)
    assert [f[0] for f in forms] == ["place_id", "name_coordinate", "name_country"]
    assert forms[0][1]["keyword"] == "place_id:PID"


def test_coordinates_are_only_offered_when_both_are_present():
    forms = build_lookup_bodies("PID", "Acme Plumbing", 34.0, None)
    assert [f[0] for f in forms] == ["place_id", "name_country"]


def test_a_nameless_prospect_still_gets_the_place_id_rung():
    assert [f[0] for f in build_lookup_bodies("PID")] == ["place_id"]


def test_a_prospect_with_no_keys_at_all_yields_no_ladder():
    """`fetch_place_info` turns this into a named error rather than posting an empty task."""
    assert build_lookup_bodies("", None) == []


def test_every_rung_carries_a_language():
    for _, body in build_lookup_bodies("PID", "Acme", 34.0, -118.2):
        assert body["language_code"] == "en"


# --- walking the ladder ------------------------------------------------------------------
#
# The rungs are free until one is accepted (DataForSEO does not bill a rejected task), which is
# what makes runtime discovery cheaper than another round of guessing. These cover that the walk
# stops at the first acceptance and remembers it.

import asyncio

from api.services.dataforseo_client import DataForSEOClient


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeHttp:
    """Answers each POST from a scripted queue and records the keyword it was asked for."""

    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.keywords = []

    async def post(self, path, json):
        self.keywords.append(json[0]["keyword"])
        return _FakeResponse(self._bodies.pop(0))


def _client(bodies, settings=None):
    http = _FakeHttp(bodies)
    return DataForSEOClient(settings or object(), client=http), http


def test_the_walk_stops_at_the_first_accepted_form():
    api, http = _client([_mbi({"place_id": "p", "rating": {"votes_count": 4}})])
    got = asyncio.run(api.fetch_place_info("p", "Acme", 34.0, -118.2))
    assert got.reviews_count == 4
    assert got.form == "place_id"
    assert http.keywords == ["place_id:p"]  # the weaker rungs were never posted


def test_a_rejected_form_falls_through_to_the_next():
    api, http = _client([
        _mbi({}, status=40501),                                   # place_id form rejected
        _mbi({"place_id": "p", "rating": {"votes_count": 4}}),     # name+coords accepted
    ])
    got = asyncio.run(api.fetch_place_info("p", "Acme", 34.0, -118.2))
    assert got.form == "name_coordinate"
    assert http.keywords == ["place_id:p", "Acme"]


def test_the_accepted_form_is_remembered_for_later_places():
    """Discovery is a property of the account, not of the place. Re-walking the ladder for all
    twenty lookups would work, but it would also mean twenty rejected tasks for no new
    information."""
    api, http = _client([
        _mbi({}, status=40501),
        _mbi({"place_id": "p", "rating": {"votes_count": 4}}),
        _mbi({"place_id": "q", "rating": {"votes_count": 7}}),
    ])
    asyncio.run(api.fetch_place_info("p", "Acme", 34.0, -118.2))
    got = asyncio.run(api.fetch_place_info("q", "Beta", 34.1, -118.3))
    assert got.reviews_count == 7
    assert http.keywords == ["place_id:p", "Acme", "Beta"]  # no second rejected place_id task


def test_every_form_failing_reports_what_each_one_said():
    """A bare 'task failed' would send the next person back to the probe. Naming each rung's
    verdict is the difference between a debuggable failure and a repeat of this file's history."""
    api, _ = _client([_mbi({}, status=40501), _mbi({}, status=40501), _mbi({}, status=40501)])
    with pytest.raises(DataForSEOError) as exc:
        asyncio.run(api.fetch_place_info("p", "Acme", 34.0, -118.2))
    assert "place_id" in str(exc.value) and "name_country" in str(exc.value)


def test_a_prospect_with_no_lookup_key_fails_by_name():
    api, http = _client([])
    with pytest.raises(DataForSEOError) as exc:
        asyncio.run(api.fetch_place_info("", None))
    assert "no usable lookup key" in str(exc.value)
    assert http.keywords == []
