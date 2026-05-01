"""Step 9 — Silo cluster identification.

Take headings discarded with reason 'below_priority_threshold' or
'global_cap_exceeded' and cluster them into supporting article seed topics.
Reuses Step 5 embeddings — zero additional API cost.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.brief import (
    IntentType,
    SiloCandidate,
    SiloSourceHeading,
)

from .llm import cosine
from .scoring import HeadingCandidate

logger = logging.getLogger(__name__)


MIN_HEADINGS_PER_CLUSTER = 2
MIN_CLUSTER_COHERENCE = 0.60
REVIEW_RECOMMENDED_MAX = 0.70
MAX_SILO_CANDIDATES = 10
CLUSTER_LINK_THRESHOLD = 0.65  # min cosine to link two headings into same cluster


def _cluster_by_proximity(
    candidates: list[HeadingCandidate],
    link_threshold: float = CLUSTER_LINK_THRESHOLD,
) -> list[list[int]]:
    """Greedy single-link clustering by cosine similarity.

    Two headings join the same cluster if they exceed link_threshold to ANY
    member of the cluster. Returns clusters as lists of indices into `candidates`.
    """
    n = len(candidates)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        if not candidates[i].embedding:
            continue
        for j in range(i + 1, n):
            if not candidates[j].embedding:
                continue
            if cosine(candidates[i].embedding, candidates[j].embedding) >= link_threshold:
                union(i, j)

    by_root: dict[int, list[int]] = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)
    return list(by_root.values())


def _coherence(indices: list[int], candidates: list[HeadingCandidate]) -> float:
    """Average pairwise cosine similarity within a cluster."""
    if len(indices) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for x in range(len(indices)):
        for y in range(x + 1, len(indices)):
            a = candidates[indices[x]].embedding
            b = candidates[indices[y]].embedding
            if a and b:
                total += cosine(a, b)
                pairs += 1
    return total / pairs if pairs else 0.0


def _centroid_text(indices: list[int], candidates: list[HeadingCandidate]) -> str:
    """Pick the heading with highest avg similarity to the rest of the cluster."""
    if len(indices) == 1:
        return candidates[indices[0]].text
    best_idx = indices[0]
    best_avg = -1.0
    for i in indices:
        sims = []
        for j in indices:
            if i == j:
                continue
            a = candidates[i].embedding
            b = candidates[j].embedding
            if a and b:
                sims.append(cosine(a, b))
        avg = sum(sims) / len(sims) if sims else 0.0
        if avg > best_avg:
            best_avg = avg
            best_idx = i
    return candidates[best_idx].text


def _infer_intent(headings: list[str]) -> IntentType:
    """Cheap signal-based intent inference for cluster seeds.

    Same conflict-priority idea as Step 3 but with cluster heading text only.
    """
    blob = " ".join(h.lower() for h in headings)
    if "vs " in blob or "versus" in blob or "comparison" in blob:
        return "comparison"
    if "how to" in blob or any(h.lower().startswith("how to") for h in headings):
        return "how-to"
    import re
    if sum(1 for h in headings if re.match(r"^\s*\d+\s+", h)) >= max(2, len(headings) // 3):
        return "listicle"
    if any(kw in blob for kw in ("best", "top", "review")):
        return "informational-commercial"
    return "informational"


def identify_silos(eligible: list[HeadingCandidate]) -> tuple[list[SiloCandidate], list[HeadingCandidate]]:
    """Step 9 — cluster eligible discarded headings into silo candidates.

    `eligible` should already be filtered to discard_reasons in
    {below_priority_threshold, global_cap_exceeded}.

    Returns (silo_candidates, headings_discarded_for_low_cluster_coherence).
    """
    if not eligible:
        return ([], [])

    clusters = _cluster_by_proximity(eligible)

    silos: list[tuple[float, SiloCandidate]] = []
    low_coherence_indices: set[int] = set()

    for cluster in clusters:
        if len(cluster) < MIN_HEADINGS_PER_CLUSTER:
            continue
        coh = _coherence(cluster, eligible)
        if coh < MIN_CLUSTER_COHERENCE:
            low_coherence_indices.update(cluster)
            continue
        keyword_text = _centroid_text(cluster, eligible)
        review_recommended = coh < REVIEW_RECOMMENDED_MAX
        recommended_intent = _infer_intent([eligible[i].text for i in cluster])

        sources: list[SiloSourceHeading] = []
        for i in cluster:
            c = eligible[i]
            if c.discard_reason not in ("below_priority_threshold", "global_cap_exceeded"):
                continue
            sources.append(SiloSourceHeading(
                text=c.text,
                semantic_score=round(c.semantic_score, 4),
                heading_priority=round(c.heading_priority, 4),
                discard_reason=c.discard_reason,  # type: ignore[arg-type]
            ))
        if not sources:
            continue

        silos.append((
            coh,
            SiloCandidate(
                suggested_keyword=keyword_text,
                cluster_coherence_score=round(coh, 4),
                review_recommended=review_recommended,
                recommended_intent=recommended_intent,
                source_headings=sources,
            ),
        ))

    silos.sort(key=lambda x: x[0], reverse=True)
    selected = [s for _, s in silos[:MAX_SILO_CANDIDATES]]

    low_coherence_candidates: list[HeadingCandidate] = []
    for i in low_coherence_indices:
        c = eligible[i]
        c.discard_reason = "low_cluster_coherence"
        low_coherence_candidates.append(c)

    return (selected, low_coherence_candidates)
