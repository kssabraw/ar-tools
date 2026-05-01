"""LEGACY v1.8 tests — skipped during the v2.0 staged rollout.

The v2.0 pipeline replaces two-tier semantic clustering with coverage-
graph regions detected via Louvain community detection (graph.py, built
in Stage 2). This file stays in tree as reference for the new region-
detection tests that will replace it.

Tests for two-tier semantic clustering (CQ PRD v1.0 R1).
"""

from __future__ import annotations

import math

import pytest

pytest.skip(
    "Legacy v1.8 clustering tests; v2.0 replaces clustering.py with "
    "coverage-graph regions in Stage 2.",
    allow_module_level=True,
)

from modules.brief.clustering import (
    HARD_MERGE_THRESHOLD,
    SOFT_CLUSTER_THRESHOLD,
    assign_cluster_ids,
    cluster_candidates,
    pick_canonicals,
)
from modules.brief.scoring import HeadingCandidate


# ---- Helpers ----

def _unit_vec(seed: float, dim: int = 32) -> list[float]:
    """Deterministic unit-norm vector. Tiny seed jitter → very high cosine."""
    raw = [math.sin(seed * (i + 1)) + math.cos(seed * (i + 2)) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def _candidate(text: str, *, seed: float, priority: float = 0.5,
               serp_freq: int = 1, position: float = 5.0,
               source: str = "serp") -> HeadingCandidate:
    c = HeadingCandidate(
        text=text,
        source=source,  # type: ignore[arg-type]
        serp_frequency=serp_freq,
        avg_serp_position=position,
    )
    c.embedding = _unit_vec(seed)
    c.heading_priority = priority
    return c


# ---- Tier-1 (hard merge) ----

def test_near_identical_embeddings_collapse_into_one_cluster():
    candidates = [
        _candidate(f"What is TikTok Shop variant {i}", seed=1.0 + i * 0.0001, priority=0.6)
        for i in range(5)
    ]
    result = cluster_candidates(candidates)
    assert len(result.clusters) == 1
    assert len(result.clusters[0]) == 5
    assert result.soft_pairs == []


def test_distinct_embeddings_stay_separate():
    candidates = [
        _candidate("Topic A", seed=1.0),
        _candidate("Topic B", seed=10.0),
        _candidate("Topic C", seed=50.0),
    ]
    result = cluster_candidates(candidates)
    # Each candidate is its own cluster (no pair exceeds the soft threshold)
    assert len(result.clusters) == 3
    assert all(len(c) == 1 for c in result.clusters)


def test_canonical_picked_by_highest_priority():
    a = _candidate("Lower priority paraphrase", seed=1.0, priority=0.3)
    b = _candidate("Higher priority paraphrase", seed=1.001, priority=0.8)
    c = _candidate("Middle priority paraphrase", seed=1.002, priority=0.5)
    candidates = [a, b, c]

    result = cluster_candidates(candidates)
    assert len(result.clusters) == 1

    assign_cluster_ids(candidates, result.clusters)
    canonicals, losers = pick_canonicals(candidates, result.clusters)

    assert len(canonicals) == 1
    assert canonicals[0].text == "Higher priority paraphrase"
    assert canonicals[0].is_canonical is True
    assert len(canonicals[0].cluster_variants) == 2
    assert len(losers) == 2
    assert all(l.discard_reason == "semantic_duplicate_of_higher_priority_h2" for l in losers)


def test_cluster_signals_roll_up_onto_canonical():
    """SERP frequency sums; LLM consensus takes max."""
    a = _candidate("Variant A", seed=1.0, priority=0.7, serp_freq=3, position=2.0)
    b = _candidate("Variant B", seed=1.0001, priority=0.5, serp_freq=4, position=4.0)
    c = _candidate("Variant C", seed=1.0002, priority=0.4, serp_freq=2, position=6.0)
    a.llm_fanout_consensus = 1
    b.llm_fanout_consensus = 3
    c.llm_fanout_consensus = 2
    candidates = [a, b, c]

    result = cluster_candidates(candidates)
    assign_cluster_ids(candidates, result.clusters)
    canonicals, losers = pick_canonicals(candidates, result.clusters)

    canonical = canonicals[0]
    assert canonical.serp_frequency == 9  # 3 + 4 + 2
    assert canonical.llm_fanout_consensus == 3  # max
    # weighted avg position: (2*3 + 4*4 + 6*2) / (3+4+2) = 34/9 ≈ 3.78
    assert canonical.avg_serp_position is not None
    assert abs(canonical.avg_serp_position - 34 / 9) < 0.01


def test_cluster_evidence_carries_variant_text_and_url():
    a = _candidate("Higher priority variant", seed=1.0, priority=0.8)
    b = _candidate("Lower priority variant", seed=1.0001, priority=0.4)
    a.source_urls = ["https://example.com/a"]
    b.source_urls = ["https://example.com/b"]

    candidates = [a, b]
    result = cluster_candidates(candidates)
    assign_cluster_ids(candidates, result.clusters)
    canonicals, _ = pick_canonicals(candidates, result.clusters)

    canonical = canonicals[0]
    assert canonical.text == "Higher priority variant"
    assert len(canonical.cluster_variants) == 1
    variant = canonical.cluster_variants[0]
    assert variant.text == "Lower priority variant"
    assert variant.source_url == "https://example.com/b"
    assert variant.cosine_to_canonical >= HARD_MERGE_THRESHOLD


# ---- Tier-2 (soft cluster band) ----

def test_soft_pairs_collected_in_band():
    """Build candidates that sit between the soft and hard thresholds.

    Hand-crafted vectors give controlled cosine values; we don't rely on
    the trig helper for this case.
    """
    a = HeadingCandidate(text="A", source="serp")
    b = HeadingCandidate(text="B", source="serp")
    a.embedding = [1.0, 0.0, 0.0]
    # cosine ≈ 0.78 — squarely in the soft band
    b.embedding = [0.78, 0.625, 0.0]
    a.heading_priority = b.heading_priority = 0.5

    result = cluster_candidates([a, b])
    assert len(result.clusters) == 2  # not auto-merged
    assert len(result.soft_pairs) == 1
    assert result.soft_pairs[0].cosine >= SOFT_CLUSTER_THRESHOLD
    assert result.soft_pairs[0].cosine < HARD_MERGE_THRESHOLD


def test_below_soft_threshold_no_pair_recorded():
    a = HeadingCandidate(text="A", source="serp")
    b = HeadingCandidate(text="B", source="serp")
    a.embedding = [1.0, 0.0, 0.0]
    b.embedding = [0.0, 1.0, 0.0]  # cosine = 0
    a.heading_priority = b.heading_priority = 0.5

    result = cluster_candidates([a, b])
    assert result.soft_pairs == []


# ---- Edge cases ----

def test_empty_input():
    result = cluster_candidates([])
    assert result.clusters == []
    assert result.soft_pairs == []


def test_single_candidate():
    c = _candidate("solo", seed=1.0)
    result = cluster_candidates([c])
    assert len(result.clusters) == 1
    assert result.clusters[0] == [0]
    assert result.soft_pairs == []


def test_candidate_without_embedding_excluded_from_pairing():
    a = _candidate("with emb", seed=1.0)
    b = HeadingCandidate(text="no emb", source="serp")
    b.heading_priority = 0.4
    # b.embedding stays empty
    result = cluster_candidates([a, b])
    # Both stay separate because b has no vector to compare
    assert len(result.clusters) == 2


def test_audited_tiktok_shop_paraphrase_cluster_collapses():
    """The exact failure mode from the 2026-05-01 audit:

    9 H2s all paraphrasing 'what is tiktok shop' must collapse to 1 canonical.
    """
    paraphrases = [
        "What is TikTok Shop",
        "What exactly is TikTok Shop",
        "Demystifying TikTok Shop",
        "TikTok Shop Discover the Future",
        "What is TikTok Shop and How to Make Money",
        "Everything About TikTok Shop for Marketers",
        "What is TikTok Shop and Why is it Important",
        "Explained: What is TikTok Shop",
        "Introducing TikTok Shop",
    ]
    candidates = [
        _candidate(t, seed=1.0 + i * 0.00001, priority=0.5 + i * 0.01)
        for i, t in enumerate(paraphrases)
    ]
    # Plus a genuinely distinct topic
    candidates.append(_candidate("How to set up TikTok Shop ads", seed=20.0, priority=0.6))

    result = cluster_candidates(candidates)
    assign_cluster_ids(candidates, result.clusters)
    canonicals, losers = pick_canonicals(candidates, result.clusters)

    # 9 paraphrases → 1 cluster + 1 distinct = 2 canonicals total
    assert len(canonicals) == 2
    big_cluster = max(canonicals, key=lambda c: len(c.cluster_variants))
    assert len(big_cluster.cluster_variants) == 8  # 9 - 1 canonical
    assert len(losers) == 8
    assert all(l.discard_reason == "semantic_duplicate_of_higher_priority_h2" for l in losers)
    assert all(l.semantic_duplicate_of_cluster == big_cluster.cluster_id for l in losers)
