"""Step 7.5 — Anchor-slot reservation (Brief Generator PRD v2.1).

Per the proposal accepted alongside Phase 1: before generic MMR runs
(Step 8), each anchor slot from the intent template tries to claim its
best-fitting candidate. The match score is the dot product (= cosine,
since both vectors are unit-normalized) between the slot's anchor
embedding and the candidate's heading embedding.

Behavior:
  - For each anchor in template.anchor_slots, find the candidate with
    the highest cosine to the anchor embedding that has not already
    been reserved by an earlier slot.
  - A candidate must score above `MIN_ANCHOR_COSINE` to be reserved.
    Below the floor we'd be force-fitting an off-topic candidate into a
    procedural slot, which is worse than letting plain MMR pick.
  - Region uniqueness AND inter-heading thresholds are still enforced
    at reservation time so a reserved slot can never violate Step 8's
    invariants.

The module returns:
  - `reserved`: list[Candidate] — preserved in slot order, ready to feed
    `select_h2s_mmr` as pre-selected entries.
  - `unmatched_slot_indices`: list[int] — slots that found no candidate
    above the floor; logged so operators can spot pools that genuinely
    lack procedural coverage (a how-to keyword whose candidate pool is
    all definitional, for example).

The downstream MMR loop continues to fill the remaining target slots
from the unreserved pool with the existing region/inter-heading rules.

Anchor embeddings:
  - Embedded once per run via `embed_batch_large` (a single API call).
  - Empty `anchor_slots` → `embed_anchor_slots` returns [], reservation
    returns empty `reserved`, and the pipeline falls through to plain
    MMR. This is the documented behavior for `listicle` / `news` /
    `local-seo` templates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from models.brief import IntentFormatTemplate

from .graph import Candidate
from .llm import embed_batch_large

logger = logging.getLogger(__name__)


# Floor below which an anchor will leave its slot empty rather than
# reserve a poor-fit candidate. 0.55 mirrors the brief-wide
# title-relevance floor; the slot is essentially asking "is this
# candidate at least as relevant to the *phase* as a generic candidate
# is to the *title*?".
MIN_ANCHOR_COSINE = 0.55


EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass
class AnchorReservation:
    """Output of `reserve_anchor_slots`.

    `reserved` preserves the order of the template's anchor slots — when
    `template.ordering == "strict_sequential"` (e.g. how-to), this means
    the reserved H2s already arrive in narrative order and the
    downstream `reorder_how_to` LLM call becomes a no-op for these.

    `unmatched_slot_indices` records anchors that didn't find a
    candidate above MIN_ANCHOR_COSINE. The pipeline logs these so a
    persistent pattern (e.g. always missing the "iterate" anchor for
    how-to keywords) can guide threshold tuning.
    """

    reserved: list[Candidate] = field(default_factory=list)
    unmatched_slot_indices: list[int] = field(default_factory=list)


def _cosine_unit(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


async def embed_anchor_slots(
    template: IntentFormatTemplate,
    *,
    embed_fn: Optional[EmbedFn] = None,
) -> list[list[float]]:
    """Embed every anchor in `template.anchor_slots` (single API call).

    Returns a list of unit-normalized embeddings aligned to
    `template.anchor_slots` order. Returns [] when the template has no
    anchor slots — callers must handle the empty case.

    On embedding failure: logs and returns [] (Step 7.5 is best-effort —
    we never abort the run because anchor embedding flaked).
    """
    if not template.anchor_slots:
        return []
    fn = embed_fn or embed_batch_large
    try:
        return await fn(list(template.anchor_slots))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "brief.anchor.embed_failed",
            extra={"intent": template.intent, "error": str(exc)},
        )
        return []


def reserve_anchor_slots(
    eligible: list[Candidate],
    template: IntentFormatTemplate,
    anchor_embeddings: list[list[float]],
    *,
    inter_heading_threshold: float = 0.75,
    min_anchor_cosine: float = MIN_ANCHOR_COSINE,
) -> AnchorReservation:
    """Reserve each anchor slot's best-fitting candidate.

    Constraints applied at reservation time (mirror Step 8's invariants):
      - Region uniqueness: at most one reservation per region_id.
      - Inter-heading anti-redundancy: a candidate already too similar
        (dot > inter_heading_threshold) to a previously reserved
        candidate is skipped.
      - Anchor-fit floor: cosine(candidate, anchor) must exceed
        `min_anchor_cosine` or the slot is left empty.

    Order: anchors are processed in the template's listed order. With
    `ordering == "strict_sequential"` this places the reserved H2s in
    narrative order automatically.

    Pure function: candidates are NOT mutated. Reserved candidates are
    returned by reference; the caller is responsible for excluding them
    from the MMR pool.
    """
    if not eligible or not template.anchor_slots or not anchor_embeddings:
        return AnchorReservation()
    if len(anchor_embeddings) != len(template.anchor_slots):
        # Embedding step partially failed — be conservative.
        logger.warning(
            "brief.anchor.embedding_count_mismatch",
            extra={
                "anchor_count": len(template.anchor_slots),
                "embedding_count": len(anchor_embeddings),
            },
        )
        return AnchorReservation()

    reserved: list[Candidate] = []
    unmatched: list[int] = []
    reserved_ids: set[int] = set()
    reserved_regions: set[str] = set()
    reserved_embeddings: list[list[float]] = []

    for slot_idx, anchor_emb in enumerate(anchor_embeddings):
        if not anchor_emb:
            unmatched.append(slot_idx)
            continue

        best_score = -float("inf")
        best_idx: Optional[int] = None
        for i, cand in enumerate(eligible):
            if id(cand) in reserved_ids:
                continue
            if cand.region_id is None or cand.region_id in reserved_regions:
                continue
            if not cand.embedding:
                continue
            # Anti-redundancy guard — never reserve a candidate that
            # would violate Step 8's pairwise threshold once it's in
            # the selected set.
            if reserved_embeddings:
                max_pairwise = max(
                    _cosine_unit(cand.embedding, prior)
                    for prior in reserved_embeddings
                )
                if max_pairwise > inter_heading_threshold:
                    continue
            score = _cosine_unit(cand.embedding, anchor_emb)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx is None or best_score < min_anchor_cosine:
            unmatched.append(slot_idx)
            logger.debug(
                "brief.anchor.unmatched",
                extra={
                    "slot_index": slot_idx,
                    "anchor": template.anchor_slots[slot_idx],
                    "best_score": (
                        round(best_score, 4) if best_score > -float("inf") else None
                    ),
                    "min_anchor_cosine": min_anchor_cosine,
                },
            )
            continue

        chosen = eligible[best_idx]
        reserved.append(chosen)
        reserved_ids.add(id(chosen))
        if chosen.region_id is not None:
            reserved_regions.add(chosen.region_id)
        reserved_embeddings.append(chosen.embedding)
        logger.debug(
            "brief.anchor.reserved",
            extra={
                "slot_index": slot_idx,
                "anchor": template.anchor_slots[slot_idx],
                "heading": chosen.text,
                "score": round(best_score, 4),
                "region_id": chosen.region_id,
            },
        )

    logger.info(
        "brief.anchor.reservation_complete",
        extra={
            "intent": template.intent,
            "anchor_count": len(template.anchor_slots),
            "reserved_count": len(reserved),
            "unmatched_count": len(unmatched),
        },
    )
    return AnchorReservation(reserved=reserved, unmatched_slot_indices=unmatched)
