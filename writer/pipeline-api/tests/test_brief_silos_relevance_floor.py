"""Regression tests for the relevance-floor singleton path in
identify_silos (PRD §5 Step 12 — extension).

Production observation that motivated this path: runs whose SERP is
dominated by restatement clusters (e.g., "what is a tiktok shop")
produce zero silos because:
  - All non-contributing regions get eliminated as `region_restates_title`
  - No scope-verification rejects exist
  - Below-relevance-floor candidates are filtered before reaching silos

Surfacing below_relevance_floor candidates as singleton silos lets the
viability LLM make the final call on whether they're substantive
enough to ship.
"""

from __future__ import annotations

import math

from models.brief import IntentType
from modules.brief.graph import Candidate, RegionInfo
from modules.brief.silos import (
    MIN_CLUSTER_COHERENCE,
    SINGLETON_COHERENCE,
    identify_silos,
)


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _cand(text: str, embedding: list[float], *, discard_reason=None,
          serp_frequency: int = 15, llm_fanout_consensus: int = 3,
          heading_priority: float = 0.5) -> Candidate:
    c = Candidate(text=text, source="serp")  # type: ignore[arg-type]
    c.embedding = _normalize(embedding)
    c.title_relevance = 0.4  # below the 0.55 floor
    c.heading_priority = heading_priority
    c.discard_reason = discard_reason
    c.serp_frequency = serp_frequency
    c.llm_fanout_consensus = llm_fanout_consensus
    return c


def test_relevance_floor_reject_becomes_singleton_silo():
    """A below_relevance_floor candidate with healthy search demand
    becomes a singleton silo with routed_from='relevance_floor_reject'."""
    rejects = [
        _cand("Best ecommerce platforms 2026", [0.0, 1.0, 0.0],
              discard_reason="below_relevance_floor"),
    ]
    silos, low = identify_silos(
        regions=[],
        candidate_pool=[],
        contributing_region_ids=set(),
        scope_rejects=[],
        relevance_rejects=rejects,
    )
    assert len(silos) == 1
    assert silos[0].suggested_keyword == "Best ecommerce platforms 2026"
    assert silos[0].routed_from == "relevance_floor_reject"
    assert silos[0].cluster_coherence_score == SINGLETON_COHERENCE
    assert len(silos[0].source_headings) == 1
    assert low == []


def test_relevance_floor_reject_with_low_search_demand_filtered():
    """Singleton candidates with both low demand AND low priority don't
    surface as silos. Tightened in v2.4: now requires both demand <
    threshold AND heading_priority < strong-priority bypass (0.30) AND
    non-fanout source. The test fixture sets heading_priority below the
    bypass to exercise the rejection path."""
    rejects = [
        _cand("Random low-signal text", [0.0, 1.0, 0.0],
              discard_reason="below_relevance_floor",
              serp_frequency=0,           # → 0 contribution from frequency
              llm_fanout_consensus=0,     # → 0 contribution from consensus
              heading_priority=0.10),     # below 0.30 strong-priority bypass
    ]
    silos, _ = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[], relevance_rejects=rejects,
    )
    assert silos == []


def test_relevance_floor_path_skips_above_restatement_ceiling():
    """Candidates discarded as `above_restatement_ceiling` restate the
    parent title — they are NOT silo candidates and must be skipped
    even when passed in via relevance_rejects."""
    rejects = [
        _cand("TikTok Shop overview", [1.0, 0.0, 0.0],
              discard_reason="above_restatement_ceiling"),
    ]
    silos, _ = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[], relevance_rejects=rejects,
    )
    assert silos == []


def test_relevance_floor_path_combines_with_other_paths():
    """Cluster + scope + relevance-floor singletons all coexist in the
    output, capped at max_candidates by descending coherence."""
    pool = [
        _cand("TikTok Shop ad creatives", [0.0, 0.9, 0.0]),
        _cand("TikTok Shop ad copy patterns", [0.0, 0.95, 0.05]),
        _cand("TikTok Shop ad budget tips", [0.0, 0.9, 0.1]),
    ]
    regions = [
        RegionInfo(
            region_id="region_2", member_indices=[0, 1, 2],
            centroid=[], density=3, source_diversity=1,
            centroid_title_distance=0.65, information_gain_signal=0.5,
            eliminated=False, elimination_reason=None, is_singleton=False,
        ),
    ]
    relevance_rejects = [
        _cand("Best ecommerce platforms 2026", [0.0, 0.0, 1.0],
              discard_reason="below_relevance_floor"),
        _cand("Social commerce trends", [0.0, 0.0, 1.0],
              discard_reason="below_relevance_floor"),
    ]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(),
        scope_rejects=[],
        relevance_rejects=relevance_rejects,
    )
    routed = sorted(s.routed_from for s in silos)
    assert routed == ["non_selected_region", "relevance_floor_reject", "relevance_floor_reject"]


def test_relevance_floor_path_default_empty_param():
    """Backward compat: omitting relevance_rejects entirely behaves
    exactly like passing an empty list."""
    silos, _ = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[],
    )
    assert silos == []
