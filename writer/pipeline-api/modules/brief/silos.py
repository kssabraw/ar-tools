"""Step 12 — Silo Cluster Identification (Brief Generator v2.0).

Implements PRD §5 Step 12. Reuses regions from Step 5 — zero additional
embedding or clustering cost over what's already been computed.

Inputs (PRD §5 Step 12):
  - Regions from Step 5 that did NOT contribute a selected H2 to the
    final outline. Eliminated regions (off_topic, restates_title) are
    skipped — their members are already in `discarded_headings` with
    the right reason and they're not useful seeds.
  - Candidates flagged with discard_reason="scope_verification_out_of_scope"
    from Step 8.5. These become singleton silo candidates because they
    almost made it into the brief and clearly represent a different
    article (high-confidence silo seeds).

Per region:
  cluster_coherence_score = average pairwise cosine between region members
  suggested_keyword       = centroid heading (highest avg sim to others)
  recommended_intent      = signal-based mapping over region heading patterns
  routed_from             = "non_selected_region"

Per scope reject (singleton):
  cluster_coherence_score = 1.0  (singleton convention from PRD §5 Step 12)
  suggested_keyword       = original heading text
  recommended_intent      = signal-based on the heading text
  routed_from             = "scope_verification"

Cluster quality rules (PRD §5 Step 12 + §11):
  - Minimum 2 headings per cluster (singletons from scope_verification exempt)
  - Minimum cluster_coherence_score = 0.60 (regions below: discarded as
    discard_reason="low_cluster_coherence")
  - Maximum 10 silo candidates per brief (highest coherence wins)
  - review_recommended = True when 0.60 ≤ coherence < 0.70
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from models.brief import (
    IntentType,
    SiloCandidate,
    SiloSourceHeading,
)

from .graph import Candidate, RegionInfo

logger = logging.getLogger(__name__)


MIN_HEADINGS_PER_CLUSTER = 2
MIN_CLUSTER_COHERENCE = 0.60
REVIEW_RECOMMENDED_MAX = 0.70
MAX_SILO_CANDIDATES = 10
SINGLETON_COHERENCE = 1.0


def _coherence(indices: list[int], pool: list[Candidate]) -> float:
    """Average pairwise cosine within a region.

    Embeddings are unit-normalized (Step 5.1) so cosine == dot product.
    Singletons return 0.0 — caller handles them via the convention path.
    """
    if len(indices) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for x in range(len(indices)):
        for y in range(x + 1, len(indices)):
            a = pool[indices[x]].embedding
            b = pool[indices[y]].embedding
            if a and b:
                total += sum(p * q for p, q in zip(a, b))
                pairs += 1
    return total / pairs if pairs else 0.0


def _centroid_heading(indices: list[int], pool: list[Candidate]) -> str:
    """Pick the heading with highest avg cosine to the rest of the region."""
    if not indices:
        return ""
    if len(indices) == 1:
        return pool[indices[0]].text

    best_idx = indices[0]
    best_avg = -float("inf")
    for i in indices:
        sims = []
        for j in indices:
            if i == j:
                continue
            a = pool[i].embedding
            b = pool[j].embedding
            if a and b:
                sims.append(sum(p * q for p, q in zip(a, b)))
        avg = sum(sims) / len(sims) if sims else 0.0
        if avg > best_avg:
            best_avg = avg
            best_idx = i
    return pool[best_idx].text


def _infer_intent(headings: list[str]) -> IntentType:
    """Cheap heading-pattern intent inference for silo seeds.

    Same priority logic as the legacy v1.7 path; preserved verbatim
    because PRD §14.2 lists silo cluster quality rules as unchanged.
    """
    blob = " ".join(h.lower() for h in headings)
    if "vs " in blob or "versus" in blob or "comparison" in blob:
        return "comparison"
    if "how to" in blob or any(h.lower().startswith("how to") for h in headings):
        return "how-to"
    if sum(1 for h in headings if re.match(r"^\s*\d+\s+", h)) >= max(2, len(headings) // 3):
        return "listicle"
    if any(kw in blob for kw in ("best", "top", "review")):
        return "informational-commercial"
    return "informational"


def _make_source_heading(c: Candidate) -> SiloSourceHeading:
    """Convert a Candidate into the SiloSourceHeading shape."""
    return SiloSourceHeading(
        text=c.text,
        source=c.source,
        title_relevance=round(c.title_relevance, 4),
        heading_priority=round(c.heading_priority, 4),
        discard_reason=c.discard_reason,  # type: ignore[arg-type]
    )


def identify_silos(
    *,
    regions: list[RegionInfo],
    candidate_pool: list[Candidate],
    contributing_region_ids: set[str],
    scope_rejects: list[Candidate],
    min_coherence: float = MIN_CLUSTER_COHERENCE,
    review_threshold: float = REVIEW_RECOMMENDED_MAX,
    max_candidates: int = MAX_SILO_CANDIDATES,
) -> tuple[list[SiloCandidate], list[Candidate]]:
    """Build silo candidates from non-contributing regions + scope rejects.

    Args:
        regions: every RegionInfo from Step 5 (eliminated regions are
            silently skipped — they're already in discarded_headings).
        candidate_pool: the candidate list whose indices RegionInfo
            members reference (i.e. the input to build_coverage_graph).
        contributing_region_ids: region_ids that contributed at least
            one H2 to the FINAL post-scope-verification outline. Those
            regions are excluded from silo consideration.
        scope_rejects: candidates with
            discard_reason="scope_verification_out_of_scope". Each
            becomes a singleton silo with routed_from="scope_verification".
        min_coherence, review_threshold, max_candidates: see PRD §5 Step 12.

    Returns:
        (silos, low_coherence_candidates):
            silos: the chosen SiloCandidate list (≤ max_candidates).
            low_coherence_candidates: members of regions that fell below
              min_coherence; their discard_reason is set to
              "low_cluster_coherence" so the orchestrator can route them
              into discarded_headings.
    """
    silos_with_score: list[tuple[float, SiloCandidate]] = []
    low_coherence: list[Candidate] = []

    # ---- non-selected, non-eliminated regions ----
    for region in regions:
        if region.eliminated:
            continue
        if region.region_id in contributing_region_ids:
            continue
        if region.density < MIN_HEADINGS_PER_CLUSTER:
            # Singletons from this path are not silo material (PRD §5 §12)
            continue

        members = list(region.member_indices)
        coh = _coherence(members, candidate_pool)
        if coh < min_coherence:
            for idx in members:
                cand = candidate_pool[idx]
                cand.discard_reason = "low_cluster_coherence"
                low_coherence.append(cand)
            logger.info(
                "brief.silo.low_coherence",
                extra={
                    "region_id": region.region_id,
                    "coherence": round(coh, 4),
                    "threshold": min_coherence,
                    "members": region.density,
                },
            )
            continue

        seed_text = _centroid_heading(members, candidate_pool)
        member_cands = [candidate_pool[i] for i in members]
        recommended_intent = _infer_intent([c.text for c in member_cands])
        review_recommended = coh < review_threshold

        silo = SiloCandidate(
            suggested_keyword=seed_text,
            cluster_coherence_score=round(coh, 4),
            review_recommended=review_recommended,
            recommended_intent=recommended_intent,
            routed_from="non_selected_region",
            source_headings=[_make_source_heading(c) for c in member_cands],
        )
        silos_with_score.append((coh, silo))

    # ---- scope-verification singleton rejects ----
    for cand in scope_rejects:
        if cand.discard_reason != "scope_verification_out_of_scope":
            continue
        recommended_intent = _infer_intent([cand.text])
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,  # high-confidence, doesn't need review
            recommended_intent=recommended_intent,
            routed_from="scope_verification",
            source_headings=[_make_source_heading(cand)],
        )
        # Singletons sit at the top of the priority list (coherence 1.0)
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- cap at max_candidates by descending coherence ----
    silos_with_score.sort(key=lambda x: x[0], reverse=True)
    selected = [s for _, s in silos_with_score[:max_candidates]]

    logger.info(
        "brief.silo.complete",
        extra={
            "input_region_count": len(regions),
            "contributing_region_count": len(contributing_region_ids),
            "scope_reject_count": len(scope_rejects),
            "low_coherence_dropped": len(low_coherence),
            "silos_returned": len(selected),
        },
    )
    return selected, low_coherence
