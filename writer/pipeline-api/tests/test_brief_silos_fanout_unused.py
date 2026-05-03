"""Tests for the LLM-fanout-unused silo path in identify_silos.

Motivation: production runs were producing zero silos because the
search-demand floor (0.30) is computed from SERP frequency + LLM-fanout
consensus + PAA/autocomplete/reddit signals — and a singleton sourced
purely from `llm_fanout_*` rarely clears the floor on its own. The
fanout LLMs themselves are a demand signal, so candidates whose source
is `llm_fanout_*` and that didn't get used as an H2 are surfaced as
silos with `routed_from="llm_fanout_unused"`, bypassing the demand
floor. The Step 12.4 viability LLM still gates the final list.
"""

from __future__ import annotations

import math

from modules.brief.graph import Candidate
from modules.brief.silos import (
    SINGLETON_COHERENCE,
    _is_fanout_source,
    identify_silos,
)


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _fanout_cand(
    text: str,
    *,
    source: str = "llm_fanout_chatgpt",
    discard_reason=None,
    serp_frequency: int = 0,
    llm_fanout_consensus: int = 1,
) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.embedding = _normalize([1.0, 0.0, 0.0])
    c.title_relevance = 0.6
    c.heading_priority = 0.5
    c.discard_reason = discard_reason
    c.serp_frequency = serp_frequency
    c.llm_fanout_consensus = llm_fanout_consensus
    return c


def test_is_fanout_source_helper():
    assert _is_fanout_source("llm_fanout_chatgpt") is True
    assert _is_fanout_source("llm_fanout_claude") is True
    assert _is_fanout_source("llm_fanout_gemini") is True
    assert _is_fanout_source("llm_fanout_perplexity") is True
    assert _is_fanout_source("serp") is False
    assert _is_fanout_source("paa") is False
    assert _is_fanout_source("llm_response_chatgpt") is False
    assert _is_fanout_source("autocomplete") is False
    assert _is_fanout_source("") is False


def test_unrouted_fanout_candidate_becomes_silo():
    """A fanout candidate sitting in candidate_pool with no discard
    reason and not in any cluster gets surfaced as a llm_fanout_unused
    silo — bypassing the search-demand floor that would normally drop
    it (low fanout-only signal)."""
    fanout = _fanout_cand("How to set up a tiktok shop")
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[fanout],
        contributing_region_ids=set(),
        scope_rejects=[],
    )
    assert len(silos) == 1
    assert silos[0].routed_from == "llm_fanout_unused"
    assert silos[0].suggested_keyword == "How to set up a tiktok shop"
    assert silos[0].cluster_coherence_score == SINGLETON_COHERENCE


def test_non_fanout_unrouted_candidate_not_routed():
    """A non-fanout candidate with no discard reason should NOT be
    surfaced via the fanout-unused path."""
    serp_cand = _fanout_cand(
        "Random heading", source="serp", llm_fanout_consensus=0
    )
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[serp_cand],
        contributing_region_ids=set(),
        scope_rejects=[],
    )
    assert silos == []


def test_fanout_relevance_floor_reject_bypasses_demand():
    """Fanout candidate that fell below the relevance floor with weak
    aux signals would normally fail the demand check (0.30) — the
    fanout source bypass surfaces it via the relevance_floor_reject
    path instead of dropping it."""
    fanout_reject = _fanout_cand(
        "Adjacent fanout topic",
        discard_reason="below_relevance_floor",
        serp_frequency=0,
        llm_fanout_consensus=1,  # 0.25 * (1/4) = 0.0625 — below 0.30 floor
    )
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[],
        contributing_region_ids=set(),
        scope_rejects=[],
        relevance_rejects=[fanout_reject],
    )
    assert len(silos) == 1
    assert silos[0].routed_from == "relevance_floor_reject"


def test_fanout_scope_verification_reject_bypasses_demand():
    fanout_reject = _fanout_cand(
        "Out of scope fanout topic",
        discard_reason="scope_verification_out_of_scope",
        serp_frequency=0,
        llm_fanout_consensus=1,
    )
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[],
        contributing_region_ids=set(),
        scope_rejects=[fanout_reject],
    )
    assert len(silos) == 1
    assert silos[0].routed_from == "scope_verification"


def test_fanout_already_routed_not_double_emitted():
    """A fanout candidate routed via scope_verification should not also
    appear via the llm_fanout_unused fallback pass."""
    fanout = _fanout_cand(
        "Single fanout topic",
        discard_reason="scope_verification_out_of_scope",
        serp_frequency=20,  # passes demand floor on its own
    )
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[fanout],
        contributing_region_ids=set(),
        scope_rejects=[fanout],
    )
    assert len(silos) == 1
    assert silos[0].routed_from == "scope_verification"


def test_non_fanout_below_relevance_floor_still_filtered_by_demand():
    """Non-fanout candidate below relevance floor with no demand should
    still be filtered (the bypass is fanout-only)."""
    serp_cand = _fanout_cand(
        "Weak serp heading",
        source="serp",
        discard_reason="below_relevance_floor",
        serp_frequency=0,
        llm_fanout_consensus=0,
    )
    silos, _ = identify_silos(
        regions=[],
        candidate_pool=[],
        contributing_region_ids=set(),
        scope_rejects=[],
        relevance_rejects=[serp_cand],
    )
    assert silos == []
