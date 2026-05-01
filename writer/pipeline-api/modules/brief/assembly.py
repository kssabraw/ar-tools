"""Step 11 — Structure Assembly (Brief Generator v2.0).

Implements PRD §5 Step 11 — same shape as v1.7 but operates on the v2
Candidate type and writes the v2 HeadingItem schema (no cluster_id /
cluster_evidence — those are gone in v2.0).

Output:
  - H1: exact-match seed keyword
  - H2 sequence per intent (capped at 6 unless intent ∈ {listicle, how-to})
  - Up to 2 H3s per H2; authority gap H3s land under their best-match H2
  - FAQ block as a synthesized H2 + question H3s (outside the global cap)
  - Global cap: 15 (default) or 20 (uncapped intents)

The function returns (heading_structure, candidates_cut_by_global_cap).
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from models.brief import (
    FAQItem,
    HeadingItem,
    IntentType,
)

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


UNCAPPED_INTENTS = {"listicle", "how-to"}
H2_CAP_DEFAULT = 6
GLOBAL_CAP_CAPPED = 15
GLOBAL_CAP_UNCAPPED = 20
MAX_H3_PER_H2 = 2

# Per PRD §5 Step 11 the parent-H2 attachment for non-authority H3s
# requires a minimum cosine of 0.55 (matches v1.7 behavior).
MIN_H3_TO_H2_SIMILARITY = 0.55


def _cosine_unit(a: list[float], b: list[float]) -> float:
    """Dot product — embeddings are unit-normalized so cosine == dot."""
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def attach_h3s(
    h2s: list[Candidate],
    authority_h3s: list[Candidate],
    h3_pool: list[Candidate],
) -> dict[int, list[Candidate]]:
    """Attach up to MAX_H3_PER_H2 H3s to each H2.

    Authority gap H3s land under the most-similar H2 (cosine on
    embeddings). They displace the lowest-priority H3 already placed if
    the slot is full — exempt H3s have priority over priority-only H3s.

    Then regular H3s fill remaining slots: each H3 is attached to its
    best-similarity H2 with capacity, provided cosine ≥ MIN_H3_TO_H2_SIMILARITY.
    """
    attached: dict[int, list[Candidate]] = {i: [] for i in range(len(h2s))}

    # Authority gap H3s first — cap-displacing
    for ah in authority_h3s:
        if not h2s:
            continue
        if not ah.embedding:
            attached[0].append(ah)
            continue
        best_idx = 0
        best_sim = -1.0
        for i, h2 in enumerate(h2s):
            if not h2.embedding:
                continue
            sim = _cosine_unit(ah.embedding, h2.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        if len(attached[best_idx]) >= MAX_H3_PER_H2:
            # Drop the weakest non-authority H3 to make room
            attached[best_idx].sort(key=lambda c: c.heading_priority)
            attached[best_idx].pop(0)
        attached[best_idx].append(ah)

    # Non-authority H3 pool — fill remaining slots by best-similarity H2
    h3_ranked = sorted(h3_pool, key=lambda c: c.heading_priority, reverse=True)
    for h3 in h3_ranked:
        if not h3.embedding:
            continue
        best_idx = -1
        best_sim = -1.0
        for i, h2 in enumerate(h2s):
            if len(attached[i]) >= MAX_H3_PER_H2:
                continue
            if not h2.embedding:
                continue
            sim = _cosine_unit(h3.embedding, h2.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        if best_idx >= 0 and best_sim >= MIN_H3_TO_H2_SIMILARITY:
            attached[best_idx].append(h3)

    return attached


LLMJsonFn = Callable[..., Awaitable]


async def reorder_how_to(
    h2s: list[Candidate],
    keyword: str,
    *,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> list[Candidate]:
    """For how-to intent: reorder H2s into setup → execution → validation.

    Falls back to the original (priority) order on any failure — never
    aborts the run.
    """
    if len(h2s) <= 2:
        return h2s
    call = llm_json_fn or claude_json
    items = [{"i": i, "text": h.text} for i, h in enumerate(h2s)]
    system = (
        "You are organizing how-to tutorial steps into the correct sequential order. "
        "Order them so prerequisites and setup come first, main execution next, "
        "validation/verification last. "
        'Respond with: {"order": [i, i, i, ...]} where each i is the original index.'
    )
    try:
        result = await call(system, f"Topic: {keyword}\nSteps:\n{items}", max_tokens=300)
        order = result.get("order") if isinstance(result, dict) else None
        if isinstance(order, list) and len(order) == len(h2s):
            seen: set[int] = set()
            reordered: list[Candidate] = []
            for idx in order:
                if isinstance(idx, int) and 0 <= idx < len(h2s) and idx not in seen:
                    reordered.append(h2s[idx])
                    seen.add(idx)
            if len(reordered) == len(h2s):
                return reordered
    except Exception as exc:
        logger.warning("brief.how_to.reorder_failed", extra={"error": str(exc)})
    return h2s


def _to_heading_item(
    c: Candidate,
    *,
    level: str,
    order: int,
    heading_type: str = "content",
) -> HeadingItem:
    """Convert a v2 Candidate into the API-shape HeadingItem."""
    return HeadingItem(
        level=level,  # type: ignore[arg-type]
        text=c.text,
        type=heading_type,  # type: ignore[arg-type]
        source=c.source,
        original_source=c.original_source,
        title_relevance=round(c.title_relevance, 4),
        exempt=c.exempt,
        serp_frequency=c.serp_frequency,
        avg_serp_position=(
            round(c.avg_serp_position, 2) if c.avg_serp_position is not None else None
        ),
        llm_fanout_consensus=c.llm_fanout_consensus,
        information_gain_score=round(c.information_gain_score, 4),
        heading_priority=round(c.heading_priority, 4),
        region_id=c.region_id,
        scope_classification=c.scope_classification,
        order=order,
    )


def assemble_structure(
    *,
    keyword: str,
    intent: IntentType,
    h2s: list[Candidate],
    h3_attachments: dict[int, list[Candidate]],
    faqs: list[FAQItem],
) -> tuple[list[HeadingItem], list[Candidate]]:
    """Build the final HeadingItem list with order numbers and the global cap.

    Args:
        keyword: seed used as the H1 text.
        intent: drives global cap (15 vs 20).
        h2s: ordered list of selected H2 candidates (Step 8 + how-to reorder).
        h3_attachments: per-H2-index list of attached H3 candidates.
        faqs: the final FAQ items (already ordered by select_faqs).

    Returns:
        (heading_structure, cap_cuts) where cap_cuts are H2/H3 candidates
        that fell off because of the global cap and need to be reflected
        in `discarded_headings` with discard_reason='global_cap_exceeded'.
    """
    cap = GLOBAL_CAP_UNCAPPED if intent in UNCAPPED_INTENTS else GLOBAL_CAP_CAPPED

    items: list[HeadingItem] = []
    cut: list[Candidate] = []
    order = 0

    # H1: exact-match seed keyword
    order += 1
    items.append(HeadingItem(
        level="H1",
        text=keyword,
        type="content",
        source="serp",
        order=order,
    ))

    used = 0
    for i, h2 in enumerate(h2s):
        if used >= cap:
            cut.append(h2)
            cut.extend(h3_attachments.get(i, []))
            continue
        order += 1
        used += 1
        items.append(_to_heading_item(h2, level="H2", order=order))

        for h3 in h3_attachments.get(i, []):
            if used >= cap:
                cut.append(h3)
                continue
            order += 1
            used += 1
            items.append(_to_heading_item(h3, level="H3", order=order))

    # FAQ section (outside the cap)
    if faqs:
        order += 1
        items.append(HeadingItem(
            level="H2",
            text="Frequently Asked Questions",
            type="faq-header",
            source="synthesized",
            order=order,
        ))
        for faq in faqs:
            order += 1
            items.append(HeadingItem(
                level="H3",
                text=faq.question,
                type="faq-question",
                source="synthesized",
                order=order,
            ))

    return items, cut
