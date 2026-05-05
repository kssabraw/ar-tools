"""Step 8 — Constrained H2 Selection via MMR (Brief Generator v2.0).

Implements the greedy Maximum Marginal Relevance algorithm with hard
constraints from PRD §5 Step 8. This is the v2.0 mechanism that
mathematically prevents the paraphrase-H2 and topical-clone outline
failure modes documented in PRD §1.

Hard constraints (any violation eliminates a candidate from the round):
  1. REGION UNIQUENESS — at most one selected H2 per coverage-graph
     region (PRD §5.5). Topical-clone outlines die here.
  2. INTER-HEADING ANTI-REDUNDANCY — pairwise cosine to any already-
     selected H2 must be ≤ inter_heading_threshold (default 0.75).
     Paraphrase outlines die here.

Soft objective (selects the best survivor each round):

    mmr_score = mmr_lambda · priority_score
              − (1 − mmr_lambda) · max_pairwise_cosine_to_selected

`priority_score` comes from Step 7 (compute_priority); embeddings come
from Step 5 (embed_with_gates). Both are unit-normalized so the
pairwise cosine is a dot product.

Shortfall policy (PRD §5 Step 8):
  If the loop terminates before reaching `target_count`, return what we
  have and flag `shortfall=True` with reason "constraints_exhausted_
  eligible_pool". DO NOT relax thresholds or invent synthetic H2s — the
  PRD is emphatic that an honest 4-H2 brief beats a padded 6-H2 brief.

Each non-selected eligible candidate gets `discard_reason =
"below_priority_threshold"` set in place — they lost the MMR competition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .graph import Candidate

logger = logging.getLogger(__name__)


SHORTFALL_EXHAUSTED = "constraints_exhausted_eligible_pool"


@dataclass
class SelectionResult:
    """Output of `select_h2s_mmr`.

    `not_selected` carries every eligible candidate that lost the MMR
    competition — each already has `discard_reason` stamped to
    "below_priority_threshold". The orchestrator routes them into the
    discard list (and feeds non-eliminated regions into silos).
    """

    selected: list[Candidate]
    not_selected: list[Candidate]
    shortfall: bool = False
    shortfall_reason: Optional[str] = None
    rounds_run: int = 0


def select_h2s_mmr(
    eligible: list[Candidate],
    target_count: int,
    inter_heading_threshold: float = 0.75,
    mmr_lambda: float = 0.7,
    *,
    pre_reserved: Optional[list[Candidate]] = None,
) -> SelectionResult:
    """Select up to `target_count` H2s under hard constraints (PRD §5 Step 8).

    Pre-conditions:
      - Every candidate in `eligible` must have `embedding` populated
        (unit-normalized) and `heading_priority` computed (Step 7).
      - Every candidate must have `region_id` populated (Step 5.5).
      - `eligible` is the post-region-elimination pool — gates and
        region-off-topic / region-restates-title cuts already applied
        upstream.
      - `pre_reserved` (PRD v2.1 Step 7.5): candidates already chosen by
        the anchor-slot reservation pass. They appear at the head of
        `selected` in their input order, and their regions/embeddings
        seed the MMR loop's hard-constraint state. The caller is
        responsible for excluding them from `eligible`.

    Behavior:
      - Pre-reserved candidates fill the first slots in input order; MMR
        fills the remaining `target_count - len(pre_reserved)` slots.
      - Greedy: each MMR round picks the surviving candidate with the
        highest mmr_score against the union of (pre-reserved + already-
        selected-by-MMR).
      - Region uniqueness and inter-heading constraints are HARD —
        violators are skipped, never penalized.
      - When no surviving candidate exists, the loop exits and shortfall
        is flagged.

    Argument validation:
      - target_count <= 0 returns empty selection without iterating.
      - mmr_lambda must be in [0, 1]; values outside raise ValueError.
      - len(pre_reserved) > target_count raises ValueError — the caller
        passed more anchors than slots to fill.
    """
    if not 0.0 <= mmr_lambda <= 1.0:
        raise ValueError(f"mmr_lambda must be in [0, 1]; got {mmr_lambda}")
    pre_reserved = list(pre_reserved or [])
    if len(pre_reserved) > target_count > 0:
        raise ValueError(
            f"pre_reserved count ({len(pre_reserved)}) exceeds target_count ({target_count})"
        )
    if target_count <= 0:
        return SelectionResult(
            selected=list(pre_reserved),
            not_selected=list(eligible),
            shortfall=False,
            shortfall_reason=None,
            rounds_run=0,
        )

    # Each candidate has a region_id by contract; if any are missing we
    # surface the bug early rather than letting them coast through every
    # round (they'd never be region-blocked, biasing selection).
    missing_region = [c.text for c in eligible if c.region_id is None]
    if missing_region:
        raise ValueError(
            "select_h2s_mmr requires region_id on every eligible candidate; "
            f"missing on: {missing_region!r}"
        )
    pre_missing_region = [c.text for c in pre_reserved if c.region_id is None]
    if pre_missing_region:
        raise ValueError(
            "select_h2s_mmr requires region_id on every pre_reserved candidate; "
            f"missing on: {pre_missing_region!r}"
        )

    # Seed MMR state with the pre-reserved candidates so subsequent
    # selections respect region uniqueness and inter-heading thresholds
    # against them.
    selected: list[Candidate] = list(pre_reserved)
    selected_regions: set[str] = {
        c.region_id for c in pre_reserved if c.region_id is not None
    }
    selected_embeddings: list[list[float]] = [
        c.embedding for c in pre_reserved if c.embedding
    ]
    pool: list[Candidate] = list(eligible)
    rounds = 0

    while pool and len(selected) < target_count:
        rounds += 1
        best_score = -float("inf")
        best_idx: Optional[int] = None
        best_redundancy = 0.0

        for i, cand in enumerate(pool):
            # HARD: region uniqueness
            if cand.region_id in selected_regions:
                continue

            # HARD: inter-heading anti-redundancy
            if selected_embeddings:
                max_pairwise = max(
                    sum(a * b for a, b in zip(cand.embedding, sel_emb))
                    for sel_emb in selected_embeddings
                )
                if max_pairwise > inter_heading_threshold:
                    continue
                redundancy = max_pairwise
            else:
                redundancy = 0.0

            mmr = (
                mmr_lambda * cand.heading_priority
                - (1.0 - mmr_lambda) * redundancy
            )

            if mmr > best_score:
                best_score = mmr
                best_idx = i
                best_redundancy = redundancy

        if best_idx is None:
            # No surviving candidate — every remaining one violates a
            # hard constraint. Accept the shortfall.
            logger.info(
                "brief.mmr.shortfall",
                extra={
                    "selected_count": len(selected),
                    "target_count": target_count,
                    "remaining_pool_size": len(pool),
                    "reason": SHORTFALL_EXHAUSTED,
                },
            )
            break

        chosen = pool.pop(best_idx)
        selected.append(chosen)
        selected_regions.add(chosen.region_id)  # type: ignore[arg-type]
        selected_embeddings.append(chosen.embedding)
        logger.debug(
            "brief.mmr.selected",
            extra={
                "round": rounds,
                "heading": chosen.text,
                "priority": round(chosen.heading_priority, 4),
                "redundancy": round(best_redundancy, 4),
                "mmr_score": round(best_score, 4),
                "region_id": chosen.region_id,
            },
        )

    # Stamp discard_reason on the losers (PRD §5 Step 8 Discarded
    # headings clause). Anything still in `pool` was either never picked
    # (lost the MMR competition) or violated a hard constraint when it
    # was its turn — either way the reason is below_priority_threshold.
    for loser in pool:
        loser.discard_reason = "below_priority_threshold"

    shortfall = len(selected) < target_count
    result = SelectionResult(
        selected=selected,
        not_selected=pool,
        shortfall=shortfall,
        shortfall_reason=SHORTFALL_EXHAUSTED if shortfall else None,
        rounds_run=rounds,
    )

    logger.info(
        "brief.mmr.complete",
        extra={
            "selected_count": len(selected),
            "target_count": target_count,
            "rounds": rounds,
            "shortfall": shortfall,
            "regions_used": len(selected_regions),
            "inter_heading_threshold": inter_heading_threshold,
            "mmr_lambda": mmr_lambda,
        },
    )

    return result
