"""Step 7.6 — LLM heading quality scoring tests (PRD v2.4).

Validates the bell-curve LLM scoring pass that runs after compute_priority
and folds a 0-1 quality score into `heading_priority` via a 70/30
vector/LLM blend.

Test surface:
- weight=0 disables the stage entirely (no LLM call, no mutations)
- top_k=0 / empty candidates → skip
- Top-K selection by current heading_priority
- Per-axis score clamping (out-of-range, non-int, bool, missing)
- Blend math: heading_priority = (1-w)*old + w*quality
- LLM call exception → no abort, no mutations
- Malformed response (no scores list, empty list) → no abort, no mutations
- Distribution summary populated for log line
"""

from __future__ import annotations

import pytest

from modules.brief.graph import Candidate
from modules.brief.llm_scoring import (
    SCORE_MAX,
    LLMScoringResult,
    _clamp_score,
    _normalize_quality,
    score_top_candidates_llm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cand(text: str, priority: float) -> Candidate:
    c = Candidate(text=text, source="serp")  # type: ignore[arg-type]
    c.heading_priority = priority
    return c


def _mock(response):
    async def _call(system, user, **kw):
        if isinstance(response, Exception):
            raise response
        return response
    return _call


# ---------------------------------------------------------------------------
# Score clamping unit tests
# ---------------------------------------------------------------------------


def test_clamp_score_in_range():
    assert _clamp_score(0) == 0
    assert _clamp_score(1) == 1
    assert _clamp_score(2) == 2
    assert _clamp_score(3) == 3


def test_clamp_score_out_of_range_clamps():
    assert _clamp_score(-1) == 0
    assert _clamp_score(7) == 3
    assert _clamp_score(100) == 3


def test_clamp_score_rejects_non_int():
    assert _clamp_score("2") is None
    assert _clamp_score(None) is None
    assert _clamp_score(2.5) is None  # non-integer float
    # bool is technically int in Python — must be excluded explicitly
    assert _clamp_score(True) is None
    assert _clamp_score(False) is None


def test_clamp_score_accepts_integer_floats():
    """LLMs sometimes emit `2.0` instead of `2`; treat as integer."""
    assert _clamp_score(2.0) == 2


def test_normalize_quality_full_range():
    assert _normalize_quality(0, 0, 0) == 0.0
    assert _normalize_quality(3, 3, 3) == 1.0
    assert _normalize_quality(2, 2, 2) == pytest.approx(6 / 9)


# ---------------------------------------------------------------------------
# Skip conditions (no LLM call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weight_zero_skips_llm_call():
    cands = [_cand("h1", 0.5), _cand("h2", 0.4)]
    result = await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.0, llm_json_fn=_mock({"scores": []}),
    )
    assert result.skipped_reason == "weight_zero"
    assert result.llm_called is False
    assert cands[0].heading_priority == 0.5  # untouched


@pytest.mark.asyncio
async def test_top_k_zero_skips_llm_call():
    cands = [_cand("h1", 0.5)]
    result = await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.3, top_k=0, llm_json_fn=_mock({"scores": []}),
    )
    assert result.skipped_reason == "top_k_zero"
    assert result.llm_called is False


@pytest.mark.asyncio
async def test_empty_candidates_skips():
    result = await score_top_candidates_llm(
        [], keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock({"scores": []}),
    )
    assert result.skipped_reason == "empty_candidates"


# ---------------------------------------------------------------------------
# Top-K selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_top_k_get_scored():
    """Five candidates, top_k=3 → only the three highest-priority ones
    are sent to the LLM and get scores applied."""
    cands = [
        _cand("h1 (lowest)", 0.10),
        _cand("h2", 0.20),
        _cand("h3", 0.30),
        _cand("h4", 0.40),
        _cand("h5 (highest)", 0.50),
    ]
    # LLM scores all three within its window the same — all 3s.
    response = {"scores": [
        {"index": 0, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
        {"index": 1, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
        {"index": 2, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
    ]}
    result = await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.3, top_k=3, llm_json_fn=_mock(response),
    )
    assert result.scored_count == 3
    # The two lowest-priority candidates get no LLM score (defaults stay).
    assert cands[0].llm_quality_score == 0.0
    assert cands[1].llm_quality_score == 0.0
    # The three highest-priority candidates were scored.
    scored_quality = sum(1 for c in cands if c.llm_quality_score > 0.0)
    assert scored_quality == 3


# ---------------------------------------------------------------------------
# Blend math
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blend_math_70_30_default():
    """heading_priority = 0.7 * old + 0.3 * llm_quality_score."""
    cand = _cand("h1", 0.50)  # vector priority = 0.50
    response = {"scores": [
        # All 3s → quality_score = 9/9 = 1.0
        {"index": 0, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
    ]}
    await score_top_candidates_llm(
        [cand], keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(response),
    )
    # Expected: 0.7 * 0.50 + 0.3 * 1.0 = 0.35 + 0.30 = 0.65
    assert cand.heading_priority == pytest.approx(0.65, abs=1e-6)
    assert cand.llm_quality_score == pytest.approx(1.0, abs=1e-6)
    assert cand.llm_topical_relevance == 3


@pytest.mark.asyncio
async def test_blend_with_zero_quality():
    """All zeros → quality=0 → priority drops to (1-w)*old."""
    cand = _cand("h1", 0.50)
    response = {"scores": [
        {"index": 0, "topical_relevance": 0, "engagement_value": 0, "information_depth": 0},
    ]}
    await score_top_candidates_llm(
        [cand], keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(response),
    )
    # Expected: 0.7 * 0.50 + 0.3 * 0.0 = 0.35
    assert cand.heading_priority == pytest.approx(0.35, abs=1e-6)
    assert cand.llm_quality_score == 0.0


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_exception_does_not_mutate():
    cand = _cand("h1", 0.50)
    result = await score_top_candidates_llm(
        [cand], keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(RuntimeError("api down")),
    )
    assert result.llm_called is True
    assert result.llm_failed is True
    assert cand.heading_priority == 0.50  # untouched
    assert cand.llm_quality_score == 0.0


@pytest.mark.asyncio
async def test_response_with_no_scores_array():
    cand = _cand("h1", 0.50)
    result = await score_top_candidates_llm(
        [cand], keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock({"unexpected": "shape"}),
    )
    assert result.no_valid_scores is True
    assert cand.heading_priority == 0.50


@pytest.mark.asyncio
async def test_scores_with_missing_axes_skipped():
    """Entries missing one of the three axes are ignored entirely."""
    cands = [_cand("h1", 0.50), _cand("h2", 0.40)]
    response = {"scores": [
        {"index": 0, "topical_relevance": 2},  # missing 2 axes
        {"index": 1, "topical_relevance": 2, "engagement_value": 2, "information_depth": 2},
    ]}
    await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(response),
    )
    assert cands[0].llm_quality_score == 0.0  # skipped
    assert cands[1].llm_quality_score > 0.0   # applied


@pytest.mark.asyncio
async def test_scores_with_invalid_index_skipped():
    cands = [_cand("h1", 0.50)]
    response = {"scores": [
        {"index": 99, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
        {"index": "bogus", "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
        {"index": 0, "topical_relevance": 2, "engagement_value": 2, "information_depth": 2},
    ]}
    await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(response),
    )
    # Only the valid index landed
    assert cands[0].llm_topical_relevance == 2


@pytest.mark.asyncio
async def test_score_distribution_populated():
    cands = [_cand(f"h{i}", 0.5 - 0.01 * i) for i in range(4)]
    response = {"scores": [
        {"index": 0, "topical_relevance": 3, "engagement_value": 3, "information_depth": 3},
        {"index": 1, "topical_relevance": 2, "engagement_value": 2, "information_depth": 2},
        {"index": 2, "topical_relevance": 2, "engagement_value": 1, "information_depth": 2},
        {"index": 3, "topical_relevance": 1, "engagement_value": 1, "information_depth": 1},
    ]}
    result = await score_top_candidates_llm(
        cands, keyword="kw", title="T", intent="how-to",
        weight=0.3, llm_json_fn=_mock(response),
    )
    assert "mean_quality" in result.score_distribution
    assert "min_quality" in result.score_distribution
    assert "max_quality" in result.score_distribution
    assert "top_score_share" in result.score_distribution
    # Top score share: 1 of 4 candidates hit a 3 on any axis = 0.25
    assert result.score_distribution["top_score_share"] == pytest.approx(0.25)
