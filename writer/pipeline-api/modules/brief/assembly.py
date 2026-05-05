"""Step 11 — Structure Assembly (Brief Generator v2.0.2).

Implements PRD §5 Step 11. In v2.0.2 the non-authority H3 attachment
moved to Step 8.6 (`h3_selection.py`); this module now handles only
the authority-gap reconciliation and final structure assembly.

Output:
  - H1: exact-match seed keyword
  - H2 sequence per intent (capped at 6 unless intent ∈ {listicle, how-to})
  - Up to 2 H3s per H2 (3 only when Authority Gap overflow occurred —
    PRD §5 Step 8.6 / Section 11)
  - FAQ block as a synthesized H2 + question H3s (outside the global cap)
  - Global cap: 15 (default) or 20 (uncapped intents)

`attach_authority_h3s_with_displacement` consumes the H3 attachments
produced by Step 8.6 and merges authority-gap H3s with the
priority-comparison + recursive routing rules from PRD §5 Step 8.6.
`assemble_structure` returns the final HeadingItem list plus the
candidates that fell off due to the global cap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from titlecase import titlecase

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
# When authority gap H3 cap-displacement causes overflow, the per-H2
# limit may grow by 1 (PRD §5 Step 8.6).
MAX_H3_PER_H2_WITH_AUTHORITY_OVERFLOW = 3


def _cosine_unit(a: list[float], b: list[float]) -> float:
    """Dot product — embeddings are unit-normalized so cosine == dot."""
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


@dataclass
class AuthorityAttachResult:
    """Output of `attach_authority_h3s_with_displacement`.

    `attachments` mirrors the input shape (H2-index → H3 list). Authority
    H3s sit at the start of each H2's list so the published order keeps
    them visually distinct from Step 8.6 H3s. `displaced` carries any
    Step 8.6 H3s evicted by higher-priority authority H3s — each has
    `discard_reason="displaced_by_authority_gap_h3"` stamped.
    """
    attachments: dict[int, list[Candidate]] = field(default_factory=dict)
    displaced: list[Candidate] = field(default_factory=list)


def _rank_h2s_by_similarity(
    auth_h3: Candidate,
    h2s: list[Candidate],
) -> list[int]:
    """Return H2 indices ordered by cosine to the authority H3, descending.

    H2s without embeddings sort to the end so we still produce a list
    where any choice is reachable by recursive routing.
    """
    scored: list[tuple[float, int]] = []
    for i, h2 in enumerate(h2s):
        sim = _cosine_unit(auth_h3.embedding, h2.embedding) if h2.embedding else -1.0
        scored.append((sim, i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [i for _, i in scored]


def attach_authority_h3s_with_displacement(
    *,
    h2s: list[Candidate],
    authority_h3s: list[Candidate],
    existing_attachments: dict[int, list[Candidate]],
    max_h3_per_h2: int = MAX_H3_PER_H2,
) -> AuthorityAttachResult:
    """Merge authority gap H3s into existing per-H2 H3 attachments.

    Algorithm (PRD §5 Step 8.6 — Authority Gap H3 Interaction):
      For each authority H3 in priority-desc order:
        1. Rank H2s by cosine(auth_h3, h2) descending.
        2. Walk the ranked list; first H2 with capacity (< max_h3_per_h2)
           wins → attach there.
        3. If no H2 has capacity, find the H2 where the auth H3 has the
           highest priority over the lowest-scoring existing H3:
             a. If the auth H3 outranks any existing H3, displace it
                (discard_reason="displaced_by_authority_gap_h3").
             b. Otherwise the auth H3 has the lowest priority across the
                board; place it under the most-relevant H2 anyway —
                authority H3s are never discarded (per PRD §5 Step 9).
                The H2's H3 count is allowed to exceed `max_h3_per_h2`
                by 1 in this edge case.

    Mutates the per-H2 lists in place; new attachment is inserted at
    index 0 so authority H3s read first under their parent H2.
    """
    attachments: dict[int, list[Candidate]] = {
        i: list(existing_attachments.get(i, [])) for i in range(len(h2s))
    }
    displaced: list[Candidate] = []

    # Process auth H3s in priority-desc order so the strongest ones get
    # first claim on capacity-available H2s.
    auth_sorted = sorted(
        authority_h3s,
        key=lambda c: c.heading_priority,
        reverse=True,
    )

    for ah in auth_sorted:
        if not h2s:
            continue
        ranked = _rank_h2s_by_similarity(ah, h2s)

        # 1. First H2 with capacity wins
        placed = False
        for h2_idx in ranked:
            if len(attachments[h2_idx]) < max_h3_per_h2:
                attachments[h2_idx].insert(0, ah)
                placed = True
                break
        if placed:
            continue

        # 2. Find best displacement target: the H2 where THIS auth H3
        # outranks the lowest-priority existing H3 by the largest margin.
        best_target_idx: Optional[int] = None
        best_margin = -float("inf")
        best_displacee: Optional[Candidate] = None
        for h2_idx in ranked:
            slot = attachments[h2_idx]
            if not slot:
                continue
            weakest = min(slot, key=lambda c: c.heading_priority)
            margin = ah.heading_priority - weakest.heading_priority
            if margin > best_margin:
                best_margin = margin
                best_target_idx = h2_idx
                best_displacee = weakest

        if best_target_idx is not None and best_displacee is not None and best_margin > 0:
            # 2a. Displace the weakest H3
            attachments[best_target_idx].remove(best_displacee)
            best_displacee.discard_reason = "displaced_by_authority_gap_h3"
            displaced.append(best_displacee)
            attachments[best_target_idx].insert(0, ah)
            continue

        # 2b. Auth H3 has lowest priority everywhere → keep it anyway
        # under the most-relevant H2 even if that exceeds the cap by 1.
        target = ranked[0]
        attachments[target].insert(0, ah)
        logger.info(
            "brief.authority.cap_overflow",
            extra={
                "auth_h3_text": ah.text,
                "h2_index": target,
                "new_h3_count": len(attachments[target]),
                "max_h3_per_h2": max_h3_per_h2,
            },
        )

    logger.info(
        "brief.authority.attach_complete",
        extra={
            "auth_h3_count": len(authority_h3s),
            "displaced_count": len(displaced),
        },
    )
    return AuthorityAttachResult(attachments=attachments, displaced=displaced)


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
    """Convert a v2 Candidate into the API-shape HeadingItem.

    `parent_h2_text` and `parent_relevance` are populated for H3 entries
    by Step 8.6 (`select_h3s_for_h2s`); they remain at defaults
    (None / 0.0) for H1, H2, FAQ entries, and authority gap H3s that
    landed via attach_authority_h3s_with_displacement.
    """
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
        # Step 9 Authority Agent's scope-alignment justification —
        # populated for source='authority_gap_sme' candidates only.
        scope_alignment_note=c.scope_alignment_note,
        parent_h2_text=c.parent_h2_text,
        parent_relevance=round(c.parent_relevance, 4) if c.parent_relevance else 0.0,
        # PRD v2.2 / Phase 2 — Step 8.7 H3 Parent-Fit Verification flag.
        # Populated only when the LLM tagged the H3 `marginal`; None
        # otherwise (`good` H3s and H2/H1 entries).
        parent_fit_classification=getattr(c, "parent_fit_classification", None),
        order=order,
    )


def assemble_structure(
    *,
    keyword: str,
    intent: IntentType,
    h2s: list[Candidate],
    h3_attachments: dict[int, list[Candidate]],
    faqs: list[FAQItem],
    title: Optional[str] = None,
) -> tuple[list[HeadingItem], list[Candidate]]:
    """Build the final HeadingItem list with order numbers and the global cap.

    Args:
        keyword: seed; used as a fallback H1 text only when no `title` is
            provided. Downstream callers that have a Step 3.5 title should
            pass it explicitly.
        intent: drives global cap (15 vs 20).
        h2s: ordered list of selected H2 candidates (Step 8 + how-to reorder).
        h3_attachments: per-H2-index list of attached H3 candidates.
        faqs: the final FAQ items (already ordered by select_faqs).
        title: Step 3.5 generated title (PRD §5 Step 3.5). When supplied,
            becomes the H1 text so the article reads with the
            reader-facing title rather than the raw seed keyword.

    Returns:
        (heading_structure, cap_cuts) where cap_cuts are H2/H3 candidates
        that fell off because of the global cap and need to be reflected
        in `discarded_headings` with discard_reason='global_cap_exceeded'.
    """
    cap = GLOBAL_CAP_UNCAPPED if intent in UNCAPPED_INTENTS else GLOBAL_CAP_CAPPED

    items: list[HeadingItem] = []
    cut: list[Candidate] = []
    order = 0

    # H1: prefer the Step 3.5 title (reader-facing); fall back to the
    # raw seed keyword only when no title was generated (e.g. legacy
    # callers or test fixtures that haven't supplied one).
    h1_text = (title or "").strip() or keyword
    order += 1
    items.append(HeadingItem(
        level="H1",
        text=h1_text,
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

    # Step 11.x — Title case normalization (PRD v2.0.3).
    # Last heading-text mutation in the pipeline. Applies AP/Chicago title
    # case via the `titlecase` PyPI library to every content + faq-header
    # heading. FAQ questions stay in sentence case (they end with `?` and
    # read as sentences, not headings).
    items = _apply_title_case(items)

    return items, cut


_TITLE_CASE_TYPES = {"content", "faq-header", "conclusion"}


def _apply_title_case(items: list[HeadingItem]) -> list[HeadingItem]:
    """Pass every content / faq-header / conclusion heading through
    `titlecase`. FAQ questions are left in sentence case because they
    are full sentences ending with `?`.

    Pure CPU; deterministic; idempotent (titlecase round-trips).
    """
    for h in items:
        if h.type not in _TITLE_CASE_TYPES:
            continue
        original = h.text
        if not original:
            continue
        normalized = titlecase(original)
        if normalized != original:
            h.text = normalized
            logger.debug(
                "brief.title_case.normalized",
                extra={
                    "level": h.level,
                    "type": h.type,
                    "before": original,
                    "after": normalized,
                },
            )
    return items
