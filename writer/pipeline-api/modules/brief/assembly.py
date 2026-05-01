"""Step 8 — Structure assembly.

Build the final heading_structure with H1, H2, H3 ordering and intent-aware caps.
Authority gap H3s are inserted under the most relevant H2.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.brief import (
    DiscardedHeading,
    FAQItem,
    HeadingItem,
    IntentType,
)

from .llm import claude_json, cosine
from .scoring import HeadingCandidate

logger = logging.getLogger(__name__)


UNCAPPED_INTENTS = {"listicle", "how-to"}
H2_CAP_DEFAULT = 6
GLOBAL_CAP_CAPPED = 15
GLOBAL_CAP_UNCAPPED = 20
MAX_H3_PER_H2 = 2


def select_h2s(
    candidates: list[HeadingCandidate],
    intent: IntentType,
) -> tuple[list[HeadingCandidate], list[HeadingCandidate]]:
    """Select H2s by priority. Returns (selected_h2s, leftovers)."""
    cap = float("inf") if intent in UNCAPPED_INTENTS else H2_CAP_DEFAULT
    # Authority gap H3s aren't H2 candidates; filter them out
    h2_pool = [c for c in candidates if c.source != "authority_gap_sme"]
    h2_pool.sort(key=lambda c: c.heading_priority, reverse=True)
    selected = h2_pool[: int(cap) if cap != float("inf") else len(h2_pool)]
    leftovers = h2_pool[len(selected):]
    return (selected, leftovers)


def attach_h3s(
    h2s: list[HeadingCandidate],
    authority_h3s: list[HeadingCandidate],
    h3_pool: list[HeadingCandidate],
) -> dict[int, list[HeadingCandidate]]:
    """Attach up to MAX_H3_PER_H2 H3s to each H2.

    Authority gap H3s go first under the most semantically similar H2.
    Then regular H3s fill remaining slots by priority.
    Returns map: h2_index -> list of H3 candidates (ordered).
    """
    attached: dict[int, list[HeadingCandidate]] = {i: [] for i in range(len(h2s))}

    # Place authority gap H3s under most-similar H2 (cosine on embeddings)
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
            sim = cosine(ah.embedding, h2.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        # Authority H3s displace lowest-priority H3 if cap reached
        if len(attached[best_idx]) >= MAX_H3_PER_H2:
            attached[best_idx].sort(key=lambda c: c.heading_priority)
            attached[best_idx].pop(0)
        attached[best_idx].append(ah)

    # Fill remaining H3 slots with pool (most similar to H2, by priority)
    h3_pool = sorted(h3_pool, key=lambda c: c.heading_priority, reverse=True)
    for h3 in h3_pool:
        if not h3.embedding:
            continue
        # Find H2 with capacity and best similarity
        best_idx = -1
        best_sim = -1.0
        for i, h2 in enumerate(h2s):
            if len(attached[i]) >= MAX_H3_PER_H2:
                continue
            if not h2.embedding:
                continue
            sim = cosine(h3.embedding, h2.embedding)
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        if best_idx >= 0 and best_sim >= 0.55:
            attached[best_idx].append(h3)

    return attached


async def reorder_how_to(h2s: list[HeadingCandidate], keyword: str) -> list[HeadingCandidate]:
    """For how-to intent: setup → execution → validation order.
    Uses LLM to suggest dependency order; falls back to priority order on failure.
    """
    if len(h2s) <= 2:
        return h2s
    items = [{"i": i, "text": h.text} for i, h in enumerate(h2s)]
    system = (
        "You are organizing how-to tutorial steps into the correct sequential order. "
        "Order them so prerequisites and setup come first, main execution next, "
        "validation/verification last. "
        'Respond with: {"order": [i, i, i, ...]} where each i is the original index.'
    )
    try:
        result = await claude_json(system, f"Topic: {keyword}\nSteps:\n{items}", max_tokens=300)
        order = result.get("order") if isinstance(result, dict) else None
        if isinstance(order, list) and len(order) == len(h2s):
            seen = set()
            reordered: list[HeadingCandidate] = []
            for idx in order:
                if isinstance(idx, int) and 0 <= idx < len(h2s) and idx not in seen:
                    reordered.append(h2s[idx])
                    seen.add(idx)
            if len(reordered) == len(h2s):
                return reordered
    except Exception as exc:
        logger.warning("how-to reorder failed: %s", exc)
    return h2s


def assemble_structure(
    keyword: str,
    intent: IntentType,
    h2s: list[HeadingCandidate],
    h3_attachments: dict[int, list[HeadingCandidate]],
    faqs: list[FAQItem],
) -> tuple[list[HeadingItem], list[HeadingCandidate]]:
    """Build the final HeadingItem list with order numbers, applying global cap.

    Returns (heading_structure, candidates_cut_by_global_cap).
    """
    cap = GLOBAL_CAP_UNCAPPED if intent in UNCAPPED_INTENTS else GLOBAL_CAP_CAPPED

    items: list[HeadingItem] = []
    cut: list[HeadingCandidate] = []
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
        items.append(HeadingItem(
            level="H2",
            text=h2.text,
            type="content",
            source=h2.source,
            original_source=h2.original_source,
            semantic_score=round(h2.semantic_score, 4),
            exempt=h2.exempt,
            serp_frequency=h2.serp_frequency,
            avg_serp_position=(
                round(h2.avg_serp_position, 2) if h2.avg_serp_position is not None else None
            ),
            llm_fanout_consensus=h2.llm_fanout_consensus,
            heading_priority=round(h2.heading_priority, 4),
            order=order,
        ))

        for h3 in h3_attachments.get(i, []):
            if used >= cap:
                cut.append(h3)
                continue
            order += 1
            used += 1
            items.append(HeadingItem(
                level="H3",
                text=h3.text,
                type="content",
                source=h3.source,
                original_source=h3.original_source,
                semantic_score=round(h3.semantic_score, 4),
                exempt=h3.exempt,
                serp_frequency=h3.serp_frequency,
                avg_serp_position=(
                    round(h3.avg_serp_position, 2) if h3.avg_serp_position is not None else None
                ),
                llm_fanout_consensus=h3.llm_fanout_consensus,
                heading_priority=round(h3.heading_priority, 4),
                order=order,
            ))

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

    return (items, cut)
