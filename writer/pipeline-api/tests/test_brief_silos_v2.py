"""Unit tests for Brief Generator v2.0 Step 12 - region-based silos."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate, RegionInfo
from modules.brief.silos import (
    MAX_SILO_CANDIDATES,
    MIN_CLUSTER_COHERENCE,
    REVIEW_RECOMMENDED_MAX,
    SINGLETON_COHERENCE,
    identify_silos,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _cand(text: str, embedding: list[float], source: str = "serp",
          title_relevance: float = 0.6, heading_priority: float = 0.5,
          discard_reason=None, serp_frequency: int = 15,
          llm_fanout_consensus: int = 3) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.embedding = _normalize(embedding)
    c.title_relevance = title_relevance
    c.heading_priority = heading_priority
    c.discard_reason = discard_reason
    # Defaults give a non-trivial search_demand_score (~0.40) so the 12.3
    # filter passes for tests that don't explicitly exercise it.
    c.serp_frequency = serp_frequency
    c.llm_fanout_consensus = llm_fanout_consensus
    return c


def _region(rid: str, members: list[int], eliminated: bool = False,
            elimination_reason=None) -> RegionInfo:
    return RegionInfo(
        region_id=rid,
        member_indices=members,
        centroid=[],  # unused by silo logic
        density=len(members),
        source_diversity=1,
        centroid_title_distance=0.65,
        information_gain_signal=0.5,
        eliminated=eliminated,
        elimination_reason=elimination_reason,
        is_singleton=len(members) < 2,
    )


# ----------------------------------------------------------------------
# Non-selected, non-eliminated regions become silos
# ----------------------------------------------------------------------

def test_non_selected_region_becomes_silo():
    pool = [
        _cand("How to optimize TikTok Shop", [0.9, 0.0, 0.0]),
        _cand("TikTok Shop ad campaigns", [0.95, 0.05, 0.0]),
        _cand("TikTok Shop conversion tips", [0.9, 0.1, 0.0]),
    ]
    regions = [_region("region_3", [0, 1, 2])]
    silos, low = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert len(silos) == 1
    s = silos[0]
    assert s.routed_from == "non_selected_region"
    assert s.cluster_coherence_score >= MIN_CLUSTER_COHERENCE
    assert len(s.source_headings) == 3
    assert low == []


def test_recommended_intent_inferred_from_headings():
    """How-to phrasing → how-to intent."""
    pool = [
        _cand("How to set up TikTok Shop", [0.9, 0.0]),
        _cand("How to add products to TikTok Shop", [0.95, 0.05]),
    ]
    regions = [_region("region_3", [0, 1])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert silos[0].recommended_intent == "how-to"


def test_recommended_intent_listicle_pattern():
    pool = [
        _cand("1 Choose your products", [0.9, 0.0]),
        _cand("2 Set up the storefront", [0.95, 0.05]),
        _cand("3 Launch your shop", [0.9, 0.1]),
    ]
    regions = [_region("region_3", [0, 1, 2])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert silos[0].recommended_intent == "listicle"


# ----------------------------------------------------------------------
# Selected region is excluded
# ----------------------------------------------------------------------

def test_selected_region_excluded():
    pool = [_cand("a", [0.9, 0.1]), _cand("b", [0.95, 0.05])]
    regions = [_region("region_0", [0, 1])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids={"region_0"},  # this region had an H2
        scope_rejects=[],
    )
    assert silos == []


def test_eliminated_region_excluded():
    pool = [_cand("a", [0.9, 0.1]), _cand("b", [0.95, 0.05])]
    regions = [_region("region_0", [0, 1], eliminated=True,
                       elimination_reason="off_topic")]
    silos, low = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    # Eliminated regions are silently skipped - their members are
    # already in discarded_headings via apply_region_outcomes.
    assert silos == []
    assert low == []


# ----------------------------------------------------------------------
# Singletons from non_selected_region path are excluded
# ----------------------------------------------------------------------

def test_singleton_non_selected_region_excluded():
    pool = [_cand("solo", [0.9, 0.0])]
    regions = [_region("region_3", [0])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert silos == []


# ----------------------------------------------------------------------
# Low coherence regions are dropped
# ----------------------------------------------------------------------

def test_low_coherence_region_dropped_and_routed_to_low_coherence_list():
    # Two members with cosine well below 0.60
    pool = [
        _cand("a", [1.0, 0.0]),
        _cand("b", [0.0, 1.0]),  # cosine = 0
    ]
    regions = [_region("region_3", [0, 1])]
    silos, low = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert silos == []
    assert len(low) == 2
    assert all(c.discard_reason == "low_cluster_coherence" for c in low)


# ----------------------------------------------------------------------
# Review recommended threshold
# ----------------------------------------------------------------------

def test_review_recommended_when_coherence_in_band():
    """Coherence ~0.65 (between 0.60 and 0.70) → review_recommended=True."""
    # Build vectors so pairwise cosines are around 0.65
    pool = [
        _cand("a", [1.0, 0.0, 0.0]),
        _cand("b", [0.65, 0.76, 0.0]),  # cos ~0.65
    ]
    regions = [_region("region_3", [0, 1])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert len(silos) == 1
    assert silos[0].review_recommended is True


def test_review_not_recommended_when_coherence_above_review_threshold():
    """Coherence ~0.85 → review_recommended=False."""
    pool = [
        _cand("a", [0.95, 0.05, 0.0]),
        _cand("b", [0.92, 0.10, 0.0]),  # high cos
    ]
    regions = [_region("region_3", [0, 1])]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
    )
    assert silos[0].review_recommended is False


# ----------------------------------------------------------------------
# Scope verification rejects → singleton silos
# ----------------------------------------------------------------------

def test_scope_reject_becomes_singleton_silo():
    rejected = _cand("How to game the algorithm", [0.7, 0.7],
                     source="serp",
                     discard_reason="scope_verification_out_of_scope")
    silos, _ = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[rejected],
    )
    assert len(silos) == 1
    s = silos[0]
    assert s.routed_from == "scope_verification"
    assert s.cluster_coherence_score == SINGLETON_COHERENCE
    assert s.suggested_keyword == "How to game the algorithm"
    assert s.review_recommended is False
    assert len(s.source_headings) == 1


def test_scope_reject_without_correct_reason_skipped():
    """A candidate in scope_rejects without the right discard_reason is ignored."""
    other = _cand("not a scope reject", [0.7, 0.7],
                  discard_reason="below_priority_threshold")
    silos, _ = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[other],
    )
    assert silos == []


# ----------------------------------------------------------------------
# max_candidates cap
# ----------------------------------------------------------------------

def test_max_candidates_cap_keeps_highest_coherence():
    """Build 12 regions, all valid; only top 10 by coherence survive."""
    pool = []
    regions = []
    # Region 0-9: high coherence (cosine ~0.95 between members)
    # Region 10-11: lower coherence (cosine ~0.7 between members)
    idx = 0
    for r in range(10):
        a = _cand(f"r{r}_a", [0.95, 0.05, 0.0])
        b = _cand(f"r{r}_b", [0.96, 0.06, 0.0])
        pool.extend([a, b])
        regions.append(_region(f"region_{r}", [idx, idx + 1]))
        idx += 2
    # r10/r11: cos ~0.65 between members (above MIN, below the 0.95+ pairs)
    for r in range(10, 12):
        a = _cand(f"r{r}_a", [1.0, 0.0, 0.0])
        b = _cand(f"r{r}_b", [0.65, 0.76, 0.0])
        pool.extend([a, b])
        regions.append(_region(f"region_{r}", [idx, idx + 1]))
        idx += 2

    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=[],
        max_candidates=10,
    )
    assert len(silos) == 10
    # The two lower-coherence regions are dropped
    keywords = {s.suggested_keyword for s in silos}
    assert "r10_a" not in keywords and "r10_b" not in keywords
    assert "r11_a" not in keywords and "r11_b" not in keywords


def test_scope_rejects_get_priority_at_top_of_cap():
    """Singletons (coherence 1.0) win the cap when total exceeds max."""
    pool = [
        _cand("region_a", [0.95, 0.05]),
        _cand("region_b", [0.96, 0.04]),
    ]
    regions = [_region("region_0", [0, 1])]
    rejects = [
        _cand(f"reject_{i}", [0.7, 0.7],
              discard_reason="scope_verification_out_of_scope")
        for i in range(MAX_SILO_CANDIDATES)
    ]
    silos, _ = identify_silos(
        regions=regions, candidate_pool=pool,
        contributing_region_ids=set(), scope_rejects=rejects,
        max_candidates=MAX_SILO_CANDIDATES,
    )
    # All 10 scope rejects make it; the region silo is dropped (lower coherence)
    assert len(silos) == MAX_SILO_CANDIDATES
    assert all(s.routed_from == "scope_verification" for s in silos)


# ----------------------------------------------------------------------
# Empty inputs
# ----------------------------------------------------------------------

def test_empty_inputs_returns_empty():
    silos, low = identify_silos(
        regions=[], candidate_pool=[], contributing_region_ids=set(),
        scope_rejects=[],
    )
    assert silos == []
    assert low == []


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def test_logs_complete_summary(caplog):
    pool = [
        _cand("a", [0.95, 0.05]),
        _cand("b", [0.96, 0.04]),
    ]
    regions = [_region("region_3", [0, 1])]
    with caplog.at_level("INFO", logger="modules.brief.silos"):
        identify_silos(
            regions=regions, candidate_pool=pool,
            contributing_region_ids=set(), scope_rejects=[],
        )
    assert any(r.message == "brief.silo.identification_complete" for r in caplog.records)


def test_logs_low_coherence_drop(caplog):
    pool = [
        _cand("a", [1.0, 0.0]),
        _cand("b", [0.0, 1.0]),
    ]
    regions = [_region("region_3", [0, 1])]
    with caplog.at_level("INFO", logger="modules.brief.silos"):
        identify_silos(
            regions=regions, candidate_pool=pool,
            contributing_region_ids=set(), scope_rejects=[],
        )
    assert any(r.message == "brief.silo.low_coherence" for r in caplog.records)
