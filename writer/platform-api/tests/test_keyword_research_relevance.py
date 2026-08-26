"""Unit tests for the Keyword Research Gemini relevance gate's pure logic."""

import math

from services import keyword_research_relevance as rel


def test_unit_normalize_makes_unit_vector():
    v = rel.unit_normalize([3.0, 4.0])
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9


def test_unit_normalize_zero_vector_unchanged():
    assert rel.unit_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_max_cosine_identical_is_one():
    a = rel.unit_normalize([1.0, 2.0, 3.0])
    assert abs(rel.max_cosine(a, [a]) - 1.0) < 1e-9


def test_max_cosine_orthogonal_is_zero():
    a = rel.unit_normalize([1.0, 0.0])
    b = rel.unit_normalize([0.0, 1.0])
    assert abs(rel.max_cosine(a, [b]) - 0.0) < 1e-9


def test_max_cosine_picks_best_anchor():
    a = rel.unit_normalize([1.0, 0.0])
    near = rel.unit_normalize([1.0, 0.05])
    far = rel.unit_normalize([0.0, 1.0])
    assert abs(rel.max_cosine(a, [far, near]) - rel.max_cosine(a, [near])) < 1e-9


def test_max_cosine_no_anchors_or_empty_is_zero():
    assert rel.max_cosine([], [[1.0]]) == 0.0
    assert rel.max_cosine([1.0], []) == 0.0


def test_max_cosine_skips_mismatched_dims():
    a = rel.unit_normalize([1.0, 0.0])
    assert rel.max_cosine(a, [[1.0, 0.0, 0.0]]) == 0.0  # 3-dim anchor skipped → no match


def test_contains_seed_phrase_true_when_all_seed_tokens_present():
    assert rel.contains_seed_phrase(
        "best third party claims administrator near me", ["third party claims administrator"])


def test_contains_seed_phrase_false_on_partial_overlap():
    assert not rel.contains_seed_phrase("party rentals", ["third party claims administrator"])


def test_apply_relevance_drops_below_floor_keeps_above():
    rows = [{"keyword": "third party administrator"}, {"keyword": "party rentals"},
            {"keyword": "claims software"}]
    kept, report = rel.apply_relevance(
        rows, [0.9, 0.2, 0.7], ["third party claims administrator"], floor=0.55)
    kw = {r["keyword"] for r in kept}
    assert "party rentals" not in kw
    assert {"third party administrator", "claims software"} <= kw
    assert report == {"gate": "semantic", "floor": 0.55, "scored": 3, "kept": 2, "dropped": 1}


def test_apply_relevance_attaches_score_to_every_kept_row():
    kept, _ = rel.apply_relevance(
        [{"keyword": "claims software"}], [0.71], ["claims"], floor=0.55)
    assert kept[0]["relevance_score"] == 0.71


def test_apply_relevance_rescues_phrase_containment_below_floor():
    # A keyword containing the full seed phrase is kept even at a low score.
    kept, report = rel.apply_relevance(
        [{"keyword": "third party claims administrator jobs"}],
        [0.10], ["third party claims administrator"], floor=0.55)
    assert len(kept) == 1 and report["dropped"] == 0


def test_dedupe_cap_case_insensitive_order_preserving():
    assert rel._dedupe_cap(["Roof", "roof", "gutter", "Roof", "siding"], 2) == ["Roof", "gutter"]
