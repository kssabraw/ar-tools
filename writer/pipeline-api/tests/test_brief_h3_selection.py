"""Unit tests for Brief Generator v2.0 Step 8.6 - H3 selection."""

from __future__ import annotations

import math

import pytest

from modules.brief.graph import Candidate, RegionInfo
from modules.brief.h3_selection import (
    INTER_H3_THRESHOLD,
    MAX_H3_PER_H2,
    PARENT_RELEVANCE_FLOOR,
    PARENT_RESTATEMENT_CEILING,
    select_h3s_for_h2s,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _cand(
    text: str,
    region: str,
    embedding: list[float],
    *,
    source: str = "serp",
    serp_frequency: int = 0,
    avg_serp_position=None,
    llm_fanout_consensus: int = 0,
    information_gain_score: float = 0.3,
) -> Candidate:
    c = Candidate(text=text, source=source)  # type: ignore[arg-type]
    c.region_id = region
    c.embedding = _normalize(embedding)
    c.serp_frequency = serp_frequency
    c.avg_serp_position = avg_serp_position
    c.llm_fanout_consensus = llm_fanout_consensus
    c.information_gain_score = information_gain_score
    return c


def _region(rid: str, members: list[int], centroid: list[float]) -> RegionInfo:
    return RegionInfo(
        region_id=rid,
        member_indices=members,
        centroid=_normalize(centroid),
        density=len(members),
        source_diversity=1,
        centroid_title_distance=0.65,
        information_gain_signal=0.5,
    )


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------

def test_attaches_in_band_h3_to_parent_h2():
    """An H3 in [0.60, 0.85] parent_relevance, in same region, attaches."""
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("Setup process for sellers", "region_0", [0.7, 0.7, 0.0])
    regions = [_region("region_0", [0, 1], [0.85, 0.5, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    assert res.attachments[0] == [h3]
    assert h3.parent_h2_text == "How TikTok Shop Works"
    assert 0.60 <= h3.parent_relevance <= 0.85


def test_excludes_h3_below_parent_relevance_floor():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("Off topic", "region_0", [0.4, 0.92, 0.0])  # cos ~0.4 < 0.60
    regions = [_region("region_0", [0, 1], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    assert res.attachments[0] == []
    assert h3 in res.globally_rejected
    assert h3.discard_reason == "h3_below_parent_relevance_floor"


def test_excludes_h3_above_parent_restatement_ceiling():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("How TikTok Shop Functions", "region_0", [0.99, 0.14, 0.0])
    regions = [_region("region_0", [0, 1], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    assert res.attachments[0] == []
    assert h3 in res.globally_rejected
    assert h3.discard_reason == "h3_above_parent_restatement_ceiling"


def test_excludes_h3_from_non_adjacent_region():
    """H3 in a region whose centroid isn't adjacent to the H2's region is dropped."""
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("Cooking recipes", "region_5", [0.0, 0.0, 1.0])
    regions = [
        _region("region_0", [0], [1.0, 0.0, 0.0]),
        _region("region_5", [1], [0.0, 0.0, 1.0]),  # orthogonal centroid
    ]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    # Region not allowed → never a candidate, never globally rejected
    assert res.attachments[0] == []
    assert h3 not in res.globally_rejected


def test_excludes_h3_from_adjacent_region_v22():
    """PRD v2.2 / Phase 2 - adjacent-region relaxation removed.
    H3s in a different region from the parent H2 are NOT selected
    even when the regions are highly similar (centroid cos ≥ 0.65).

    Pre-v2.2 this case would have attached the H3; v2.2 strict same-
    region keeps cross-region drift out of the parent H2's slot.
    Cross-region candidates that would have qualified can still
    surface as silos via the relevance-floor / scope paths.
    """
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("Seller onboarding", "region_1", [0.7, 0.7, 0.0])
    regions = [
        _region("region_0", [0], [0.95, 0.31, 0.0]),
        _region("region_1", [1], [0.7, 0.71, 0.0]),  # cos ~0.89 to region_0
    ]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    assert res.attachments[0] == []


# ----------------------------------------------------------------------
# Inter-H3 anti-redundancy
# ----------------------------------------------------------------------

def test_inter_h3_threshold_blocks_paraphrase():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    a = _cand("Setup process", "region_0", [0.7, 0.7, 0.0],
              llm_fanout_consensus=4)  # higher priority → wins round 1
    b = _cand("Setup procedure", "region_0", [0.71, 0.7, 0.0])  # paraphrase of a
    regions = [_region("region_0", [0, 1, 2], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[a, b], regions=regions,
    )
    assert len(res.attachments[0]) == 1  # b blocked by inter-H3 threshold
    assert a in res.attachments[0]


def test_max_two_h3s_per_h2_default():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    pool = [
        _cand(f"H3-{i}", "region_0",
              [0.7 + 0.01 * i, 0.7 - 0.01 * i, 0.05 * i])
        for i in range(5)
    ]
    regions = [_region("region_0", list(range(6)), [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=pool, regions=regions,
    )
    assert len(res.attachments[0]) <= MAX_H3_PER_H2


# ----------------------------------------------------------------------
# Multi-H2 dynamics
# ----------------------------------------------------------------------

def test_h3_can_be_evaluated_for_multiple_h2s_but_only_attached_once():
    """Same candidate competes for both H2s; first H2 to pick it wins."""
    # Vectors chosen so cos(h3, h2_a) = 0.7 and cos(h3, h2_b) = 0.7071 -
    # both inside the [0.60, 0.85] parent_relevance band.
    h2_a = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h2_b = _cand("Selling on TikTok Shop", "region_1", [0.7071, 0.7071, 0.0])
    h3 = _cand("Setup process", "region_0", [0.7, 0.3, 0.65])  # 3D
    regions = [
        _region("region_0", [0, 2], [0.95, 0.31, 0.0]),
        _region("region_1", [1], [0.71, 0.7, 0.0]),  # adjacent to region_0
    ]
    res = select_h3s_for_h2s(
        selected_h2s=[h2_a, h2_b], h3_pool=[h3], regions=regions,
    )
    # h3 is in region_0 - both H2s could pick it (region_0 same; region_1 adjacent)
    # but the global-attachment guard ensures only one H2 actually attaches it.
    total_attachments = sum(len(arr) for arr in res.attachments.values())
    assert total_attachments == 1
    assert h3 not in res.globally_rejected
    # First H2 wins (higher-priority H2s come first in selected_h2s)
    assert h3 in res.attachments[0]
    assert h3 not in res.attachments[1]


def test_h3_rejected_by_one_h2_still_eligible_for_another():
    """A heading that fails parent_relevance for H2-A but is in-band for H2-B
    should NOT appear in globally_rejected."""
    h2_a = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h2_b = _cand("Seller revenue tactics", "region_0", [0.0, 1.0, 0.0])
    # h3 unit-normalized to [0.57, 0.823, 0]:
    #   cos to h2_a = 0.57  (below 0.60 floor → rejected by H2-A)
    #   cos to h2_b = 0.823 (in band [0.60, 0.85] → accepted by H2-B)
    h3 = _cand("Pricing strategy", "region_0", [0.45, 0.65, 0.0])
    regions = [_region("region_0", [0, 1, 2], [0.5, 0.5, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2_a, h2_b], h3_pool=[h3], regions=regions,
    )
    # H3 eligible for H2-B → must NOT appear in globally_rejected
    assert h3 not in res.globally_rejected
    # And it should actually attach to H2-B
    assert h3 in res.attachments[1]
    assert h3.parent_h2_text == "Seller revenue tactics"


# ----------------------------------------------------------------------
# Selected H2s never become H3 candidates
# ----------------------------------------------------------------------

def test_selected_h2s_excluded_from_pool():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    # Same object passed in both h2 list and pool
    regions = [_region("region_0", [0], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h2], regions=regions,
    )
    assert res.attachments[0] == []


# ----------------------------------------------------------------------
# H2s without state
# ----------------------------------------------------------------------

def test_h2_missing_embedding_skipped_gracefully():
    h2 = Candidate(text="H2", source="serp")  # type: ignore[arg-type]
    h2.region_id = "region_0"  # but no embedding
    h3 = _cand("h3", "region_0", [0.7, 0.7, 0.0])
    regions = [_region("region_0", [0, 1], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    assert res.attachments[0] == []


# ----------------------------------------------------------------------
# Empty inputs
# ----------------------------------------------------------------------

def test_empty_h2s_returns_empty():
    res = select_h3s_for_h2s(selected_h2s=[], h3_pool=[], regions=[])
    assert res.attachments == {}
    assert res.globally_rejected == []
    assert res.h2s_with_zero_h3s == 0


def test_empty_h3_pool_returns_empty_attachments():
    h2 = _cand("H2", "region_0", [1.0, 0.0, 0.0])
    regions = [_region("region_0", [0], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[], regions=regions,
    )
    assert res.attachments[0] == []
    assert res.h2s_with_zero_h3s == 1


def test_h2s_with_zero_h3s_counter():
    h2_a = _cand("H2-A", "region_0", [1.0, 0.0, 0.0])
    h2_b = _cand("H2-B", "region_1", [0.0, 1.0, 0.0])
    h3 = _cand("Only fits A", "region_0", [0.7, 0.7, 0.0])
    # Make region_1 not adjacent to region_0
    regions = [
        _region("region_0", [0, 2], [1.0, 0.0, 0.0]),
        _region("region_1", [1], [0.0, 0.0, 1.0]),
    ]
    res = select_h3s_for_h2s(
        selected_h2s=[h2_a, h2_b], h3_pool=[h3], regions=regions,
    )
    assert res.h2s_with_zero_h3s == 1


# ----------------------------------------------------------------------
# Stamping
# ----------------------------------------------------------------------

def test_attached_h3_carries_parent_metadata():
    h2 = _cand("How TikTok Shop Works", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("Setup", "region_0", [0.7, 0.7, 0.0])
    regions = [_region("region_0", [0, 1], [1.0, 0.0, 0.0])]
    res = select_h3s_for_h2s(
        selected_h2s=[h2], h3_pool=[h3], regions=regions,
    )
    attached = res.attachments[0][0]
    assert attached.parent_h2_text == "How TikTok Shop Works"
    assert attached.parent_relevance > 0.0


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def test_logs_complete_summary(caplog):
    h2 = _cand("H2", "region_0", [1.0, 0.0, 0.0])
    h3 = _cand("H3", "region_0", [0.7, 0.7, 0.0])
    regions = [_region("region_0", [0, 1], [1.0, 0.0, 0.0])]
    with caplog.at_level("INFO", logger="modules.brief.h3_selection"):
        select_h3s_for_h2s(
            selected_h2s=[h2], h3_pool=[h3], regions=regions,
        )
    assert any(
        r.message == "brief.h3.selection.complete" for r in caplog.records
    )


# ----------------------------------------------------------------------
# Constants sanity
# ----------------------------------------------------------------------

def test_thresholds_match_prd():
    # PRD v2.2 / Phase 2 - floor raised 0.60 → 0.65 (drop adjacent-region
    # relaxation; tighter same-region only).
    assert PARENT_RELEVANCE_FLOOR == 0.65
    assert PARENT_RESTATEMENT_CEILING == 0.85
    assert INTER_H3_THRESHOLD == 0.78
    assert MAX_H3_PER_H2 == 2
