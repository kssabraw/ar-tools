"""Step 8.6 — H3 Selection (Brief Generator v2.0.x).

Implements PRD §5 Step 8.6. Per-H2 MMR over the candidate pool that
remains after Step 8 (the eligible pool minus the H2s themselves).

Algorithm — for each selected H2:

  1. parent_relevance = cosine(H3_candidate, H2)
  2. Filter:
       parent_relevance ∈ [0.60, 0.85]
       same region as H2, OR adjacent region with edge to H2's region
         centroid ≥ 0.65
       not already selected as an H2
  3. MMR with target=2, inter_h3_threshold=0.78, mmr_lambda=0.7,
     where each candidate's "priority" reuses the Step 7 formula but
     swaps title_relevance → parent_relevance for THIS parent H2.
  4. Accept shortfalls. Per-H2 H3 count is informational only — H3s
     are never required.

Authority gap H3s do NOT flow through this module. They run in Step 9
and Step 11 reconciles cap-displacement when an authority gap H3 is
assigned to an H2 that already has 2 H3s from this step.

Discard reason mapping (PRD §5 Step 12.1):
  parent_relevance < 0.60 → discard_reason="h3_below_parent_relevance_floor"
  parent_relevance > 0.85 → discard_reason="h3_above_parent_restatement_ceiling"
  Lost MMR → discard_reason="below_priority_threshold"

A candidate's discard_reason is only stamped if it FAILS against EVERY
selected H2 — a heading that's a great H3 for H2[2] but too close to
H2[1]'s topic should not be tagged as a global reject.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .graph import Candidate, RegionInfo

logger = logging.getLogger(__name__)


PARENT_RELEVANCE_FLOOR = 0.60
PARENT_RESTATEMENT_CEILING = 0.85
INTER_H3_THRESHOLD = 0.78
MAX_H3_PER_H2 = 2
H3_MMR_LAMBDA = 0.7

# Edge weight required for an H3 candidate's region to count as "adjacent"
# to an H2's region. Matches Step 5's coverage graph edge_threshold so
# adjacency reuses the same notion of relatedness.
ADJACENT_REGION_EDGE_WEIGHT = 0.65


def _cosine_unit(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _build_adjacent_regions_map(
    regions: list[RegionInfo],
    edge_threshold: float = ADJACENT_REGION_EDGE_WEIGHT,
) -> dict[str, set[str]]:
    """Pre-compute adjacency: region_id → set of adjacent region_ids.

    Two regions are adjacent if the cosine between their centroids exceeds
    `edge_threshold`. This is a region-level approximation of the
    coverage-graph edge concept used in Step 5.
    """
    adjacency: dict[str, set[str]] = {r.region_id: set() for r in regions}
    for i, r_i in enumerate(regions):
        if not r_i.centroid or r_i.eliminated:
            continue
        for r_j in regions[i + 1:]:
            if not r_j.centroid or r_j.eliminated:
                continue
            sim = _cosine_unit(r_i.centroid, r_j.centroid)
            if sim >= edge_threshold:
                adjacency[r_i.region_id].add(r_j.region_id)
                adjacency[r_j.region_id].add(r_i.region_id)
    return adjacency


def _h3_priority(parent_relevance: float, c: Candidate) -> float:
    """Step 7 formula with title_relevance swapped for parent_relevance.

    Mirrors `priority.compute_priority` exactly — copying the formula
    here rather than importing because the swap target is per-parent.
    """
    norm_freq = min((c.serp_frequency or 0) / 20.0, 1.0)
    if c.avg_serp_position is not None:
        position_weight = max(1.0 - ((c.avg_serp_position - 1) / 20.0), 0.0)
    else:
        position_weight = 0.5
    norm_consensus = min((c.llm_fanout_consensus or 0) / 4.0, 1.0)
    info_gain = c.information_gain_score
    return (
        0.30 * parent_relevance
        + 0.20 * norm_freq
        + 0.10 * position_weight
        + 0.20 * norm_consensus
        + 0.20 * info_gain
    )


@dataclass
class H3SelectionResult:
    """Output of `select_h3s_for_h2s`.

    `attachments` maps the H2's index in `selected_h2s` → list of H3
    Candidates (with `parent_h2_text` and `parent_relevance` stamped).

    `globally_rejected` carries candidates that failed the parent-relevance
    or restatement check against EVERY selected H2 — these get a discard
    reason and feed the `discarded_headings` list. Candidates that lost
    only the per-H2 MMR competition are stamped `below_priority_threshold`.
    """

    attachments: dict[int, list[Candidate]] = field(default_factory=dict)
    globally_rejected: list[Candidate] = field(default_factory=list)
    h2s_with_zero_h3s: int = 0


def select_h3s_for_h2s(
    *,
    selected_h2s: list[Candidate],
    h3_pool: list[Candidate],
    regions: list[RegionInfo],
    parent_relevance_floor: float = PARENT_RELEVANCE_FLOOR,
    parent_restatement_ceiling: float = PARENT_RESTATEMENT_CEILING,
    inter_h3_threshold: float = INTER_H3_THRESHOLD,
    mmr_lambda: float = H3_MMR_LAMBDA,
    max_h3_per_h2: int = MAX_H3_PER_H2,
) -> H3SelectionResult:
    """Per-H2 MMR H3 selection (PRD §5 Step 8.6).

    Pre-conditions:
      - Every H2 has `embedding` and `region_id` populated (Step 5 + 8)
      - Every H3 candidate has `embedding`, `region_id`, and the Step 7
        priority signals (`serp_frequency`, `llm_fanout_consensus`,
        `information_gain_score`, `avg_serp_position`)
      - `regions` is the full RegionInfo list from Step 5.5

    Behavior:
      - Each H2 independently runs MMR over its scope-filtered pool
      - The same H3 candidate can compete for multiple H2s; only the H2
        that picks it actually attaches it
      - Attached H3s have `parent_h2_text` and `parent_relevance` stamped
      - Lost-MMR candidates that were eligible for at least one H2 are
        NOT stamped as globally rejected — they remain available to other
        layers (e.g., authority gap pool sees them clean)
      - Candidates that were never eligible (every H2 rejected them on
        parent_relevance bounds) get the appropriate `h3_*` discard reason
    """
    if not selected_h2s:
        return H3SelectionResult()

    adjacency = _build_adjacent_regions_map(regions)

    # Track each candidate's worst-case fate across all H2s. Once any H2
    # accepts it as an MMR candidate (in-band parent_relevance + region OK),
    # it's no longer "globally rejected" even if it loses MMR everywhere.
    eligible_for_some_h2: set[int] = set()
    rejection_by_idx: dict[int, str] = {}
    selected_ids: set[int] = {id(h) for h in selected_h2s}
    # Track candidates already attached to a previous H2 so the same
    # candidate isn't placed under multiple H2s. The selected_h2s list is
    # already ordered by Step 8 MMR score, so processing left-to-right
    # gives the higher-priority H2 first claim on shared candidates.
    attached_ids: set[int] = set()

    attachments: dict[int, list[Candidate]] = {i: [] for i in range(len(selected_h2s))}

    for i, h2 in enumerate(selected_h2s):
        h2_region = h2.region_id
        if h2_region is None or not h2.embedding:
            logger.warning(
                "brief.h3.h2_missing_state",
                extra={"h2_text": h2.text},
            )
            continue
        allowed_regions = {h2_region} | adjacency.get(h2_region, set())

        # ---- per-H2 filter pass ----
        per_h2_candidates: list[tuple[Candidate, float]] = []
        for j, c in enumerate(h3_pool):
            if id(c) in selected_ids:
                continue
            if id(c) in attached_ids:
                # Already taken by an earlier H2 — counts as "eligible for
                # some H2" so it never lands in globally_rejected.
                eligible_for_some_h2.add(j)
                continue
            if not c.embedding or c.region_id is None:
                continue
            if c.region_id not in allowed_regions:
                continue
            pr = _cosine_unit(c.embedding, h2.embedding)
            if pr < parent_relevance_floor:
                rejection_by_idx.setdefault(j, "h3_below_parent_relevance_floor")
                continue
            if pr > parent_restatement_ceiling:
                rejection_by_idx.setdefault(j, "h3_above_parent_restatement_ceiling")
                continue
            eligible_for_some_h2.add(j)
            # Drop any prior rejection note: this H2 deems it in-band.
            rejection_by_idx.pop(j, None)
            per_h2_candidates.append((c, pr))

        # ---- per-H2 MMR ----
        chosen: list[Candidate] = []
        chosen_embeddings: list[list[float]] = []
        pool = list(per_h2_candidates)
        while pool and len(chosen) < max_h3_per_h2:
            best_idx: Optional[int] = None
            best_score = -float("inf")
            for k, (cand, pr) in enumerate(pool):
                if chosen_embeddings:
                    max_pairwise = max(
                        _cosine_unit(cand.embedding, e) for e in chosen_embeddings
                    )
                    if max_pairwise > inter_h3_threshold:
                        continue
                    redundancy = max_pairwise
                else:
                    redundancy = 0.0
                priority = _h3_priority(pr, cand)
                mmr = mmr_lambda * priority - (1.0 - mmr_lambda) * redundancy
                if mmr > best_score:
                    best_score = mmr
                    best_idx = k
            if best_idx is None:
                break
            cand, pr = pool.pop(best_idx)
            cand.parent_h2_text = h2.text
            cand.parent_relevance = pr
            chosen.append(cand)
            chosen_embeddings.append(cand.embedding)
            attached_ids.add(id(cand))

        attachments[i] = chosen

        logger.debug(
            "brief.h3.selection.per_h2",
            extra={
                "h2_text": h2.text,
                "h2_region": h2_region,
                "candidates_in_band": len(per_h2_candidates),
                "h3s_selected": len(chosen),
            },
        )

    # ---- Identify globally rejected candidates ----
    # Only candidates that were rejected by EVERY H2 on parent_relevance
    # bounds become "global rejects". MMR losers per H2 stay clean unless
    # they failed parent_relevance against every other H2 too.
    globally_rejected: list[Candidate] = []
    for j, c in enumerate(h3_pool):
        if id(c) in selected_ids:
            continue
        if j in eligible_for_some_h2:
            continue
        reason = rejection_by_idx.get(j)
        if reason is None:
            continue
        c.discard_reason = reason  # type: ignore[assignment]
        globally_rejected.append(c)

    h2s_with_zero_h3s = sum(1 for arr in attachments.values() if not arr)

    logger.info(
        "brief.h3.selection.complete",
        extra={
            "h2_count": len(selected_h2s),
            "total_h3s_selected": sum(len(v) for v in attachments.values()),
            "h2s_with_zero_h3s": h2s_with_zero_h3s,
            "globally_rejected_count": len(globally_rejected),
            "parent_relevance_floor": parent_relevance_floor,
            "parent_restatement_ceiling": parent_restatement_ceiling,
            "inter_h3_threshold": inter_h3_threshold,
        },
    )

    return H3SelectionResult(
        attachments=attachments,
        globally_rejected=globally_rejected,
        h2s_with_zero_h3s=h2s_with_zero_h3s,
    )
