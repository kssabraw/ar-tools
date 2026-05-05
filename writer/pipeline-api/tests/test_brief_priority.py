"""Unit tests for Brief Generator v2.0 Step 7 — heading priority scoring."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate
from modules.brief.priority import compute_priority, information_gain_score


def _make(text: str, source: str = "serp", **kw) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ----------------------------------------------------------------------
# information_gain_score tiers
# ----------------------------------------------------------------------

@pytest.mark.parametrize("source,consensus,expected", [
    # Tier 1 (1.0): non-SERP source AND consensus >= 1
    ("reddit", 1, 1.0),
    ("paa", 4, 1.0),
    ("persona_gap", 2, 1.0),
    ("autocomplete", 3, 1.0),
    ("llm_fanout_chatgpt", 1, 1.0),
    ("llm_response_claude", 1, 1.0),

    # Tier 2 (0.7): non-SERP source, no consensus
    ("reddit", 0, 0.7),
    ("paa", 0, 0.7),
    ("persona_gap", 0, 0.7),
    ("autocomplete", 0, 0.7),

    # Tier 3 (0.3): SERP only (consensus irrelevant — SERP can't have
    # llm_fanout_consensus by construction since it's not from fan-out)
    ("serp", 0, 0.3),
    ("serp", 5, 0.3),
])
def test_information_gain_tiers(source, consensus, expected):
    assert information_gain_score(source, consensus) == expected


# ----------------------------------------------------------------------
# compute_priority — formula correctness
# ----------------------------------------------------------------------

def test_priority_formula_serp_top_position():
    """SERP heading at position 1 with high frequency, mid title relevance."""
    c = _make("x", source="serp",
              title_relevance=0.70,
              serp_frequency=20,    # → norm_freq = 1.0
              avg_serp_position=1.0,  # → position_weight = 1.0
              llm_fanout_consensus=0)  # → norm_consensus = 0
    compute_priority([c])
    # 0.30*0.70 + 0.20*1.0 + 0.10*1.0 + 0.20*0 + 0.20*0.3 (serp tier)
    # = 0.21 + 0.20 + 0.10 + 0.00 + 0.06 = 0.57
    assert c.heading_priority == pytest.approx(0.57)
    assert c.information_gain_score == 0.3


def test_priority_formula_reddit_with_consensus():
    """Reddit heading also surfaced by 2 LLMs — high info-gain tier."""
    c = _make("x", source="reddit",
              title_relevance=0.65,
              serp_frequency=0,     # → 0
              avg_serp_position=None,  # → position_weight = 0.5 (neutral)
              llm_fanout_consensus=2)  # → norm_consensus = 0.5
    compute_priority([c])
    # 0.30*0.65 + 0.20*0 + 0.10*0.5 + 0.20*0.5 + 0.20*1.0 (tier 1)
    # = 0.195 + 0 + 0.05 + 0.10 + 0.20 = 0.545
    assert c.heading_priority == pytest.approx(0.545)
    assert c.information_gain_score == 1.0


def test_priority_formula_persona_gap_no_consensus():
    """Persona gap heading with no other signal — tier 2 info gain (0.7)."""
    c = _make("x", source="persona_gap",
              title_relevance=0.60,
              serp_frequency=0,
              avg_serp_position=None,
              llm_fanout_consensus=0)
    compute_priority([c])
    # 0.30*0.60 + 0 + 0.10*0.5 + 0 + 0.20*0.7 = 0.18 + 0.05 + 0.14 = 0.37
    assert c.heading_priority == pytest.approx(0.37)
    assert c.information_gain_score == 0.7


def test_priority_formula_serp_low_position():
    """SERP heading at position 20 — position_weight = 1 - 19/20 = 0.05."""
    c = _make("x", source="serp",
              title_relevance=0.65,
              serp_frequency=10,     # → norm_freq = 0.5
              avg_serp_position=20.0,  # → position_weight = 0.05
              llm_fanout_consensus=0)
    compute_priority([c])
    # 0.30*0.65 + 0.20*0.5 + 0.10*0.05 + 0 + 0.20*0.3
    # = 0.195 + 0.10 + 0.005 + 0.06 = 0.36
    assert c.heading_priority == pytest.approx(0.36)


def test_priority_position_weight_clamps_to_zero():
    """avg_serp_position > 21 yields negative weight before clamp; verify clamp."""
    c = _make("x", source="serp",
              title_relevance=0.6, serp_frequency=0,
              avg_serp_position=99.0, llm_fanout_consensus=0)
    compute_priority([c])
    # position_weight should clamp to 0, not be negative
    # Reconstruct expected: 0.30*0.6 + 0 + 0.10*0 + 0 + 0.20*0.3 = 0.24
    assert c.heading_priority == pytest.approx(0.24)


def test_priority_consensus_normalization_caps_at_1():
    """llm_fanout_consensus > 4 should still normalize to 1.0."""
    c = _make("x", source="reddit",
              title_relevance=0.6, serp_frequency=0,
              avg_serp_position=None, llm_fanout_consensus=10)
    compute_priority([c])
    # norm_consensus capped at 1.0
    # 0.30*0.6 + 0 + 0.10*0.5 + 0.20*1.0 + 0.20*1.0 = 0.18 + 0.05 + 0.20 + 0.20 = 0.63
    assert c.heading_priority == pytest.approx(0.63)


def test_priority_serp_frequency_normalization_caps_at_1():
    """serp_frequency > 20 normalizes to 1.0, not above."""
    c = _make("x", source="serp",
              title_relevance=0.7, serp_frequency=50,
              avg_serp_position=1.0, llm_fanout_consensus=0)
    compute_priority([c])
    # norm_freq capped at 1.0
    # 0.30*0.7 + 0.20*1.0 + 0.10*1.0 + 0 + 0.20*0.3 = 0.21 + 0.20 + 0.10 + 0.06 = 0.57
    assert c.heading_priority == pytest.approx(0.57)


def test_priority_idempotent():
    """Calling compute_priority twice produces the same result."""
    c = _make("x", source="reddit",
              title_relevance=0.6, serp_frequency=5,
              avg_serp_position=3.0, llm_fanout_consensus=2)
    compute_priority([c])
    first = c.heading_priority
    compute_priority([c])
    assert c.heading_priority == pytest.approx(first)


def test_priority_handles_empty_list():
    compute_priority([])  # no error


def test_priority_mutates_in_place_for_all_candidates():
    cands = [
        _make("a", source="serp", title_relevance=0.6,
              serp_frequency=10, avg_serp_position=5.0),
        _make("b", source="reddit", title_relevance=0.7,
              llm_fanout_consensus=3),
        _make("c", source="paa", title_relevance=0.65),
    ]
    compute_priority(cands)
    # All three should have non-zero priority and the right info-gain tier
    assert all(c.heading_priority > 0 for c in cands)
    assert cands[0].information_gain_score == 0.3   # serp
    assert cands[1].information_gain_score == 1.0   # reddit + consensus
    assert cands[2].information_gain_score == 0.7   # paa, no consensus


def test_priority_logs_summary(caplog):
    cands = [_make("a", title_relevance=0.6),
             _make("b", title_relevance=0.7)]
    with caplog.at_level("INFO", logger="modules.brief.priority"):
        compute_priority(cands)
    assert any(r.message == "brief.priority.computed" for r in caplog.records)


def test_priority_max_value_bounded_by_one():
    """All-perfect inputs cap the score at the sum of weights = 1.0."""
    c = _make("x", source="reddit",
              title_relevance=1.0,
              serp_frequency=20,
              avg_serp_position=1.0,
              llm_fanout_consensus=4)
    compute_priority([c])
    # 0.30*1 + 0.20*1 + 0.10*1 + 0.20*1 + 0.20*1 = 1.0
    assert c.heading_priority == pytest.approx(1.0)
    assert c.heading_priority <= 1.0
