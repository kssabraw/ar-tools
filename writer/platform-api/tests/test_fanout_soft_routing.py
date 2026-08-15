"""Soft silo routing: _active_topics (fanout relevance gate).

Hard argmax routes each keyword to a single silo, which starves silos with
overlapping anchors (a single-entity seed emptied 3 of 5 silos). Soft routing
(silo_margin > 0) additionally keeps a keyword active in every silo within the
margin of its top cosine. margin <= 0 must reproduce exact argmax."""

from fanout.pipeline.relevance import _active_topics


def test_margin_zero_is_pure_argmax():
    kw_scores = {"k": {"A": 0.80, "B": 0.60}}
    best = {"k": "A"}
    assert _active_topics(kw_scores, best, 0.0) == {"k": {"A"}}


def test_margin_zero_ignores_scores_and_uses_best_map():
    # With margin<=0 the result is derived solely from best_topic_for_kw, so a
    # keyword with no scores (embedding failed) still maps to its recorded best.
    assert _active_topics({}, {"k": "A"}, 0.0) == {"k": {"A"}}


def test_positive_margin_keeps_within_band_silos():
    kw_scores = {"k": {"A": 0.80, "B": 0.60, "C": 0.40}}
    best = {"k": "A"}
    # band = [0.80-0.25, 0.80] = [0.55, 0.80] → A and B, not C.
    assert _active_topics(kw_scores, best, 0.25) == {"k": {"A", "B"}}


def test_tight_margin_keeps_only_best():
    kw_scores = {"k": {"A": 0.80, "B": 0.60}}
    best = {"k": "A"}
    assert _active_topics(kw_scores, best, 0.10) == {"k": {"A"}}


def test_llm_reroute_is_always_included_even_below_margin():
    # The LLM rerouted "k" to B (0.60), below the raw-cosine margin band {A}.
    # The recorded best must still be kept active.
    kw_scores = {"k": {"A": 0.80, "B": 0.60}}
    best = {"k": "B"}
    assert _active_topics(kw_scores, best, 0.05) == {"k": {"A", "B"}}


def test_independent_keywords():
    kw_scores = {"k1": {"A": 0.9, "B": 0.5}, "k2": {"A": 0.5, "B": 0.52}}
    best = {"k1": "A", "k2": "B"}
    out = _active_topics(kw_scores, best, 0.05)
    assert out["k1"] == {"A"}          # B (0.5) outside [0.85, 0.9]
    assert out["k2"] == {"A", "B"}     # A (0.5) within [0.47, 0.52]
