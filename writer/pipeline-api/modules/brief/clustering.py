"""Two-tier semantic clustering of heading candidates (CQ PRD v1.0 R1).

After Step 5 (semantic scoring), candidates carry embeddings. This module
groups them into clusters of equivalent meaning so downstream stages
(polish, priority, MMR selection) operate on canonical representatives
instead of paraphrase floods.

Tier 1 (hard merge):  cosine ≥ 0.85   → auto-merge
Tier 2 (soft):        0.72 ≤ cos < 0.85 → provisional, may be confirmed
                                          via LLM arbitration in polish step
Distinct:             cosine < 0.72   → stay separate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .llm import cosine
from .scoring import HeadingCandidate

logger = logging.getLogger(__name__)


HARD_MERGE_THRESHOLD = 0.85
SOFT_CLUSTER_THRESHOLD = 0.72


@dataclass
class SoftPair:
    """A pair of headings whose cosine sits in the soft band (0.72–0.85).

    Surfaced to the polish step so the LLM can arbitrate whether they're
    paraphrases of the same idea.
    """
    a_index: int
    b_index: int
    cosine: float


@dataclass
class ClusteringResult:
    """Output of the clustering pass.

    `clusters` is a list of lists of indices into the input candidates list.
    Each cluster has its canonical chosen by the caller (after priority
    is computed). `soft_pairs` are pairs that can optionally be merged
    later by LLM arbitration.
    """
    clusters: list[list[int]]
    soft_pairs: list[SoftPair]


def _union_find_init(n: int) -> list[int]:
    return list(range(n))


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent: list[int], i: int, j: int) -> None:
    ri, rj = _find(parent, i), _find(parent, j)
    if ri != rj:
        parent[ri] = rj


def cluster_candidates(
    candidates: list[HeadingCandidate],
    hard_threshold: float = HARD_MERGE_THRESHOLD,
    soft_threshold: float = SOFT_CLUSTER_THRESHOLD,
) -> ClusteringResult:
    """Greedy single-link clustering at the hard threshold; collect soft pairs.

    Both thresholds operate on the same precomputed embeddings (from Step 5).
    The function does not pick canonicals or merge metrics - that's done by
    the caller after `compute_priority` runs on the canonicals.
    """
    n = len(candidates)
    if n <= 1:
        return ClusteringResult(clusters=[[i] for i in range(n)], soft_pairs=[])

    parent = _union_find_init(n)
    soft_pairs: list[SoftPair] = []

    # O(n^2) - fine for the pool sizes we see (typically 30–100 candidates
    # after Step 5 filtering). If pool sizes ever spike, swap for an
    # approximate-NN index, but keep deterministic ordering.
    for i in range(n):
        emb_i = candidates[i].embedding
        if not emb_i:
            continue
        for j in range(i + 1, n):
            emb_j = candidates[j].embedding
            if not emb_j:
                continue
            sim = cosine(emb_i, emb_j)
            if sim >= hard_threshold:
                _union(parent, i, j)
            elif sim >= soft_threshold:
                soft_pairs.append(SoftPair(a_index=i, b_index=j, cosine=sim))

    cluster_map: dict[int, list[int]] = {}
    for i in range(n):
        root = _find(parent, i)
        cluster_map.setdefault(root, []).append(i)

    clusters = list(cluster_map.values())
    logger.info(
        "clustering: candidates=%d hard_clusters=%d soft_pairs=%d",
        n, len(clusters), len(soft_pairs),
    )
    return ClusteringResult(clusters=clusters, soft_pairs=soft_pairs)


def assign_cluster_ids(
    candidates: list[HeadingCandidate],
    clusters: list[list[int]],
) -> None:
    """Stamp each candidate with its cluster_id.

    Cluster IDs are sequential starting at 0, ordered by the highest-priority
    candidate in the cluster (so cluster 0 is the most important cluster).
    The caller must have run `compute_priority` before this for stable
    ordering - otherwise priorities are 0.0 and cluster ordering is unstable.
    """
    # Sort clusters by max priority within them, descending
    indexed = [
        (max((candidates[i].heading_priority for i in cluster), default=0.0), cluster)
        for cluster in clusters
    ]
    indexed.sort(key=lambda x: x[0], reverse=True)

    for cid, (_, cluster) in enumerate(indexed):
        for i in cluster:
            candidates[i].cluster_id = cid


def pick_canonicals(
    candidates: list[HeadingCandidate],
    clusters: list[list[int]],
) -> tuple[list[HeadingCandidate], list[HeadingCandidate]]:
    """Select one canonical per cluster (highest heading_priority) and
    populate its `cluster_variants` list with the rest.

    Returns (canonicals, losers). Losers are the discarded duplicates
    that need to be routed into `discarded_headings` by the caller.
    SERP / LLM-fanout / position signals are rolled up onto canonicals
    via `_rollup_cluster_signals`.
    """
    canonicals: list[HeadingCandidate] = []
    losers: list[HeadingCandidate] = []

    for cluster in clusters:
        if not cluster:
            continue
        members = [candidates[i] for i in cluster]
        # Stable: pick highest priority; tiebreak on (more SERP frequency,
        # then lower avg_serp_position, then earliest source string)
        members.sort(
            key=lambda c: (
                c.heading_priority,
                c.serp_frequency,
                -(c.avg_serp_position or 999),
                -len(c.text),
            ),
            reverse=True,
        )
        canonical = members[0]
        canonical.is_canonical = True
        variants = members[1:]

        # Roll up cluster-level signals onto canonical so downstream priority
        # recompute reflects the cluster's combined SERP weight.
        _rollup_cluster_signals(canonical, variants)

        # Populate cluster_variants for downstream output
        canonical.cluster_variants = [
            ClusterVariant(
                text=v.text,
                source=v.source,
                source_url=(v.source_urls[0] if v.source_urls else None),
                source_urls=list(v.source_urls),
                avg_serp_position=v.avg_serp_position,
                cosine_to_canonical=cosine(canonical.embedding, v.embedding)
                    if (canonical.embedding and v.embedding) else 0.0,
                heading_priority=v.heading_priority,
            )
            for v in variants
        ]

        canonicals.append(canonical)
        for v in variants:
            v.discard_reason = "semantic_duplicate_of_higher_priority_h2"
            v.semantic_duplicate_of_cluster = canonical.cluster_id
            losers.append(v)

    return canonicals, losers


def _rollup_cluster_signals(
    canonical: HeadingCandidate,
    variants: list[HeadingCandidate],
) -> None:
    """Combine SERP/LLM/position signals from variants onto the canonical.

    - serp_frequency: sum across cluster (each SERP appearance counts once)
    - avg_serp_position: weighted mean by frequency
    - llm_fanout_consensus: max distinct-LLM count across cluster
    - source_urls: union of all variant URLs
    """
    total_freq = canonical.serp_frequency
    weighted_pos_sum = (
        (canonical.avg_serp_position or 0.0) * canonical.serp_frequency
        if canonical.avg_serp_position is not None else 0.0
    )
    pos_weight = canonical.serp_frequency if canonical.avg_serp_position is not None else 0

    max_consensus = canonical.llm_fanout_consensus
    url_set: list[str] = list(canonical.source_urls)
    seen_urls = set(url_set)

    for v in variants:
        total_freq += v.serp_frequency
        if v.avg_serp_position is not None:
            weighted_pos_sum += v.avg_serp_position * v.serp_frequency
            pos_weight += v.serp_frequency
        max_consensus = max(max_consensus, v.llm_fanout_consensus)
        for u in v.source_urls:
            if u not in seen_urls:
                seen_urls.add(u)
                url_set.append(u)

    canonical.serp_frequency = total_freq
    canonical.avg_serp_position = (
        weighted_pos_sum / pos_weight if pos_weight > 0 else canonical.avg_serp_position
    )
    canonical.llm_fanout_consensus = max_consensus
    canonical.source_urls = url_set


# Forward-declared in scoring.py to avoid circular imports - re-imported here
# only for the canonical's `cluster_variants` field.
from .scoring import ClusterVariant  # noqa: E402
