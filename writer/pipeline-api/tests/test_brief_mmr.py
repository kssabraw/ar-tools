"""Unit tests for Brief Generator v2.0 Step 8 — MMR selection."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate
from modules.brief.mmr import SHORTFALL_EXHAUSTED, select_h2s_mmr


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _make(text: str, region: str, priority: float, embedding: list[float],
          source: str = "serp") -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.region_id = region
    c.heading_priority = priority
    c.embedding = _normalize(embedding)
    return c


# ----------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------

def test_mmr_selects_one_per_region_in_priority_order():
    """Three regions with one strong candidate each — all selected."""
    cands = [
        _make("a1", "region_0", 0.9, [1.0, 0.0, 0.0]),
        _make("b1", "region_1", 0.8, [0.0, 1.0, 0.0]),
        _make("c1", "region_2", 0.7, [0.0, 0.0, 1.0]),
    ]
    res = select_h2s_mmr(cands, target_count=3)
    assert [c.text for c in res.selected] == ["a1", "b1", "c1"]
    assert res.shortfall is False
    assert res.not_selected == []


def test_mmr_picks_strongest_within_each_region():
    """Region with multiple members: only highest priority wins."""
    cands = [
        _make("a1", "region_0", 0.9, [1.0, 0.0, 0.0]),
        _make("a2", "region_0", 0.7, [0.99, 0.14, 0.0]),  # same region, weaker
        _make("b1", "region_1", 0.8, [0.0, 1.0, 0.0]),
    ]
    res = select_h2s_mmr(cands, target_count=2)
    selected_texts = {c.text for c in res.selected}
    assert selected_texts == {"a1", "b1"}
    # a2 lost the MMR competition (region uniqueness blocked it)
    assert any(c.text == "a2" and c.discard_reason == "below_priority_threshold"
               for c in res.not_selected)


# ----------------------------------------------------------------------
# Hard constraints
# ----------------------------------------------------------------------

def test_mmr_blocks_inter_heading_above_threshold():
    """Two candidates in different regions but with cosine > 0.75 — second blocked."""
    # Same vector but different regions → cosine = 1.0
    cands = [
        _make("a1", "region_0", 0.9, [1.0, 0.0]),
        _make("b1", "region_1", 0.8, [1.0, 0.0]),  # cos 1.0 to a1
    ]
    res = select_h2s_mmr(cands, target_count=2,
                         inter_heading_threshold=0.75)
    assert [c.text for c in res.selected] == ["a1"]
    assert res.shortfall is True
    assert res.shortfall_reason == SHORTFALL_EXHAUSTED
    # b1 is in not_selected with the discard reason set
    assert res.not_selected[0].text == "b1"
    assert res.not_selected[0].discard_reason == "below_priority_threshold"


def test_mmr_allows_pairs_below_threshold():
    """cos = 0.7 (below 0.75 threshold) → both can be selected."""
    cands = [
        _make("a1", "region_0", 0.9, [1.0, 0.0]),
        _make("b1", "region_1", 0.8, [0.7, 0.7]),  # cos ~0.7 to a1
    ]
    res = select_h2s_mmr(cands, target_count=2,
                         inter_heading_threshold=0.75)
    assert [c.text for c in res.selected] == ["a1", "b1"]
    assert res.shortfall is False


# ----------------------------------------------------------------------
# Shortfall handling
# ----------------------------------------------------------------------

def test_mmr_shortfall_when_pool_too_small():
    cands = [_make("a1", "region_0", 0.9, [1.0, 0.0])]
    res = select_h2s_mmr(cands, target_count=3)
    assert len(res.selected) == 1
    assert res.shortfall is True
    assert res.shortfall_reason == SHORTFALL_EXHAUSTED


def test_mmr_shortfall_when_all_in_one_region():
    """Five candidates but only one region — only one H2 possible."""
    cands = [
        _make(f"x{i}", "region_0", 0.9 - i * 0.1, [1.0, 0.0, 0.0])
        for i in range(5)
    ]
    res = select_h2s_mmr(cands, target_count=3)
    assert len(res.selected) == 1
    assert res.shortfall is True


def test_mmr_no_shortfall_when_target_met():
    cands = [
        _make("a1", "region_0", 0.9, [1.0, 0.0, 0.0]),
        _make("b1", "region_1", 0.8, [0.0, 1.0, 0.0]),
    ]
    res = select_h2s_mmr(cands, target_count=2)
    assert len(res.selected) == 2
    assert res.shortfall is False
    assert res.shortfall_reason is None


# ----------------------------------------------------------------------
# Empty / degenerate inputs
# ----------------------------------------------------------------------

def test_mmr_empty_eligible():
    res = select_h2s_mmr([], target_count=5)
    assert res.selected == []
    assert res.not_selected == []
    # Note: with empty input, target=5 > selected=0, so shortfall is true.
    # But since we never iterated, the orchestrator should detect this case
    # earlier (no_eligible_candidates abort). MMR returning shortfall=True
    # here is the honest outcome.
    assert res.shortfall is True


def test_mmr_target_count_zero_returns_empty():
    cands = [_make("a1", "region_0", 0.9, [1.0, 0.0])]
    res = select_h2s_mmr(cands, target_count=0)
    assert res.selected == []
    # not_selected gets the full pool back (untouched discard_reason)
    assert len(res.not_selected) == 1
    assert res.not_selected[0].discard_reason is None
    assert res.shortfall is False


def test_mmr_target_count_negative_treated_like_zero():
    cands = [_make("a1", "region_0", 0.9, [1.0, 0.0])]
    res = select_h2s_mmr(cands, target_count=-1)
    assert res.selected == []
    assert res.shortfall is False


# ----------------------------------------------------------------------
# Argument validation
# ----------------------------------------------------------------------

def test_mmr_invalid_lambda_rejected():
    with pytest.raises(ValueError):
        select_h2s_mmr([], target_count=5, mmr_lambda=1.5)
    with pytest.raises(ValueError):
        select_h2s_mmr([], target_count=5, mmr_lambda=-0.1)


def test_mmr_missing_region_id_raises():
    c = Candidate(text="x", source="serp")
    c.heading_priority = 0.5
    c.embedding = [1.0, 0.0]
    # region_id is None by default
    with pytest.raises(ValueError, match="region_id"):
        select_h2s_mmr([c], target_count=1)


# ----------------------------------------------------------------------
# Ordering and tie-breaking
# ----------------------------------------------------------------------

def test_mmr_picks_higher_priority_when_diversity_equal():
    """No prior selections → diversity penalty = 0. Highest priority wins."""
    cands = [
        _make("low", "region_0", 0.5, [1.0, 0.0]),
        _make("high", "region_1", 0.9, [0.0, 1.0]),
        _make("mid", "region_2", 0.7, [0.0, 0.0]),  # zero vec; harmless here
    ]
    res = select_h2s_mmr(cands, target_count=1)
    assert res.selected[0].text == "high"


def test_mmr_lambda_zero_pure_diversity():
    """λ=0: only diversity matters. Any region distinct from selected wins."""
    # First pick: priority irrelevant, but with no prior we just take anything.
    # Actually with λ=0 and no selection, score = 0 - 0 = 0 for everyone, ties.
    # Stable iteration order picks the first.
    cands = [
        _make("a1", "region_0", 0.5, [1.0, 0.0]),
        _make("b1", "region_1", 0.9, [0.7, 0.7]),
    ]
    res = select_h2s_mmr(cands, target_count=2, mmr_lambda=0.0,
                         inter_heading_threshold=0.99)
    # Both should be selected (different regions, cosine 0.7 < 0.99)
    assert len(res.selected) == 2


def test_mmr_lambda_one_pure_priority():
    """λ=1: priority is everything; redundancy ignored except as hard cap."""
    cands = [
        _make("a1", "region_0", 0.5, [1.0, 0.0]),
        _make("b1", "region_1", 0.9, [0.7, 0.7]),  # cos to a1 ~0.7
    ]
    res = select_h2s_mmr(cands, target_count=2, mmr_lambda=1.0,
                         inter_heading_threshold=0.75)
    # Round 1: b1 wins (priority 0.9). Round 2: a1 still passes hard cap (0.7 < 0.75).
    assert [c.text for c in res.selected] == ["b1", "a1"]


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def test_mmr_logs_complete_summary(caplog):
    cands = [_make("a", "region_0", 0.9, [1.0, 0.0])]
    with caplog.at_level("INFO", logger="modules.brief.mmr"):
        select_h2s_mmr(cands, target_count=1)
    assert any(r.message == "brief.mmr.complete" for r in caplog.records)


def test_mmr_logs_shortfall(caplog):
    cands = [
        _make("a", "region_0", 0.9, [1.0, 0.0]),
        _make("b", "region_0", 0.8, [1.0, 0.0]),  # same region → blocked
    ]
    with caplog.at_level("INFO", logger="modules.brief.mmr"):
        select_h2s_mmr(cands, target_count=2)
    assert any(r.message == "brief.mmr.shortfall" for r in caplog.records)


# ----------------------------------------------------------------------
# Integration scenario: anti-paraphrase semantics
# ----------------------------------------------------------------------

def test_mmr_blocks_paraphrase_outline_simulation():
    """Replicate the v1.7 failure mode: 5 'what is X' paraphrases,
    plus 2 distinct angle headings. With v2.0 constraints, the
    paraphrases collapse into a single H2 and the distinct ones survive.

    All 5 paraphrases are in the same region (Step 5 already would have
    given them the same region_id since they cluster tightly). MMR picks
    only the highest-priority of them and the two distinct ones.
    """
    paraphrase_vec = [0.99, 0.14, 0.0]
    distinct_a = [0.0, 1.0, 0.0]
    distinct_b = [0.0, 0.0, 1.0]
    cands = [
        _make("What is TikTok Shop", "region_0", 0.85, paraphrase_vec),
        _make("What exactly is TikTok Shop", "region_0", 0.80, paraphrase_vec),
        _make("What is a TikTok Shop seller", "region_0", 0.75, paraphrase_vec),
        _make("What is a TikTok Shop creator", "region_0", 0.70, paraphrase_vec),
        _make("What is a TikTok Shop account", "region_0", 0.65, paraphrase_vec),
        _make("How TikTok Shop works", "region_1", 0.78, distinct_a),
        _make("Who can sell on TikTok Shop", "region_2", 0.72, distinct_b),
    ]
    res = select_h2s_mmr(cands, target_count=6,
                         inter_heading_threshold=0.75)
    selected_texts = [c.text for c in res.selected]
    # Exactly one paraphrase survives (the highest-priority one)
    assert selected_texts.count("What is TikTok Shop") == 1
    assert sum(1 for t in selected_texts if "TikTok Shop" in t and "What" in t) == 1
    # Both distinct angles survive
    assert "How TikTok Shop works" in selected_texts
    assert "Who can sell on TikTok Shop" in selected_texts
    # 4 paraphrases routed to discards
    discarded_paraphrases = [
        c for c in res.not_selected if "What" in c.text and "TikTok" in c.text
    ]
    assert len(discarded_paraphrases) == 4
    assert all(c.discard_reason == "below_priority_threshold"
               for c in discarded_paraphrases)
