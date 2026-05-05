"""Step 6.7 — Per-H2 Body Length Validator (Writer PRD v1.6 / Phase 3).

Catches H2 sections shipping with empty/lightweight bodies (the audited
"two sentences and a stat before jumping to the next H2" failure mode).

Position in the pipeline:
  Runs AFTER:
    - Step 4 section writing
    - Step 5 FAQ writing
    - Step 6 conclusion writing
    - Step 6.4 CTA / Step 6.5 Key Takeaways (when implemented per PRD R4)
    - Step 6.6 paragraph length validation
    - Heading-level banned-term scan
  Runs BEFORE:
    - Step 7 citation usage reconciliation

Algorithm:
  For each H2 SECTION GROUP (parent H2 + child H3 bodies + the H3
  enrichments + authority-gap H3 entries that landed under that H2):
    1. Compute group_word_count = sum of word counts across the group,
       after stripping `{{cit_N}}` markers.
    2. If group_word_count >= min_h2_body_words: pass.
    3. Otherwise: re-run `write_h2_group` ONCE with a length-retry
       directive that names the floor and the current word count, and
       asks for additional substance (not padding) to clear it.
    4. After the retry, recompute group_word_count.
       - If now >= floor: succeeded, replace the original sections.
       - If still under: accept the original output (or the retry,
         whichever has more words) and append to
         `under_length_h2_sections` for review.

Failure-mode policy (matches Step 6.6 paragraph-length convention):
  - Never aborts the run. Empty H2 sections are recoverable in
    post-edit; aborting the whole article on a length miss is worse.
  - Retry uses a single LLM call per offending H2. Steady-state cost
    is ~zero (validator passes on most well-budgeted sections).

Inputs:
  - `article: list[ArticleSection]` — the full assembled article.
    The validator only inspects entries with `level == "H2"` +
    `type == "content"` and walks forward to collect their child H3s
    until the next H2 (or end of article).
  - `min_h2_body_words` — the floor from `format_directives`.
  - `write_h2_group_fn` — injected so callers (and tests) can supply
    an alternate implementation; defaults to the production
    `sections.write_h2_group`.
  - The full set of writer arguments needed to drive a section retry
    (keyword, intent, brief heading_structure, section_budgets,
    filtered_terms, citations, brand_voice_card, banned_regex).

Outputs:
  - `validated_article`: list[ArticleSection] with replacements applied
    where retries succeeded. The original article order is preserved.
  - `under_length_h2_sections`: list[dict] of (section_order,
    word_count, floor) for H2s still below the floor after one retry.
  - `retries_attempted` / `retries_succeeded`: counters for metadata.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from models.writer import ArticleSection, BrandVoiceCard

from .brand_placement import BrandPlacementPlan
from .reconciliation import FilteredSIETerms
from .sections import SectionWriteResult, write_h2_group

logger = logging.getLogger(__name__)


_CITATION_MARKER_RE = re.compile(r"\{\{cit_\d+\}\}")


WriteH2GroupFn = Callable[..., Awaitable[SectionWriteResult]]


@dataclass
class H2BodyLengthResult:
    """Output of `validate_h2_body_lengths`."""

    validated_article: list[ArticleSection] = field(default_factory=list)
    under_length_h2_sections: list[dict] = field(default_factory=list)
    retries_attempted: int = 0
    retries_succeeded: int = 0


def _word_count(body: str) -> int:
    """Count words in a body after stripping `{{cit_N}}` markers."""
    if not body:
        return 0
    cleaned = _CITATION_MARKER_RE.sub("", body)
    return len(cleaned.split())


def _group_word_count(group: list[ArticleSection]) -> int:
    """Sum word counts across an H2 section group (parent + H3 children)."""
    return sum(_word_count(s.body) for s in group)


@dataclass
class _H2Group:
    """An H2 parent and its consecutive H3 children in `article` order."""

    h2_index: int
    h2_section: ArticleSection
    children: list[tuple[int, ArticleSection]] = field(default_factory=list)


def _collect_h2_groups(article: list[ArticleSection]) -> list[_H2Group]:
    """Walk `article` and group each H2-content section with its
    consecutive H3-content + h1-enrichment-style children up to the
    next H2 (or to the FAQ block / conclusion / cta / takeaways, which
    end the group).

    Only `type == "content"` H2s are tracked — FAQ headers and
    conclusion H2s are left alone (they're handled by other steps).
    """
    groups: list[_H2Group] = []
    current: Optional[_H2Group] = None
    for i, section in enumerate(article):
        if section.level == "H2" and section.type == "content":
            if current is not None:
                groups.append(current)
            current = _H2Group(h2_index=i, h2_section=section)
            continue
        # Once we hit a non-content H2 (FAQ header / conclusion) or a
        # non-content section type that signals end-of-body, close out
        # the current group.
        if section.level == "H2" and section.type != "content":
            if current is not None:
                groups.append(current)
                current = None
            continue
        if section.type in {"faq-header", "faq-question", "conclusion", "cta", "key-takeaways"}:
            if current is not None:
                groups.append(current)
                current = None
            continue
        if current is None:
            continue
        if section.level == "H3" and section.type == "content":
            current.children.append((i, section))
        # Other section types (h1-enrichment, intro, etc.) are not
        # part of an H2 group — leave them alone.
    if current is not None:
        groups.append(current)
    return groups


def _retry_directive(group_words: int, floor: int) -> str:
    return (
        f"Your previous attempt produced {group_words} words for this H2 "
        f"section group. The floor is {floor} words. Add "
        f"{floor - group_words}+ words of additional SUBSTANCE — concrete "
        f"examples, evidence, or clarifying detail. Do NOT pad with filler "
        f"or repetition; if the topic genuinely doesn't support more "
        f"substantive content, prefer adding a concrete example or a brief "
        f"qualifying sentence over generic restatement."
    )


def _replace_group_in_article(
    article: list[ArticleSection],
    group: _H2Group,
    new_sections: list[ArticleSection],
) -> list[ArticleSection]:
    """Replace the H2 + its children in-place with `new_sections`.

    `new_sections` is the SectionWriteResult.sections list — one entry
    for the parent H2 and one per H3 child, in original order. We splice
    the article so the surrounding ordering (intro/FAQ/conclusion/etc.)
    stays intact.
    """
    # Determine the slice [start, end) the group occupies in `article`.
    start = group.h2_index
    end = start + 1 + len(group.children)
    # Ensure the new sections preserve order metadata. write_h2_group
    # returns ArticleSection objects with the original H2 + H3 order
    # values, so we can splice without renumbering.
    return article[:start] + list(new_sections) + article[end:]


async def validate_h2_body_lengths(
    article: list[ArticleSection],
    *,
    min_h2_body_words: int,
    keyword: str,
    intent: str,
    heading_structure: list[dict],
    section_budgets: dict[int, int],
    filtered_terms: FilteredSIETerms,
    citations: list[dict],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    placement_plan: Optional[BrandPlacementPlan] = None,
    write_h2_group_fn: Optional[WriteH2GroupFn] = None,
) -> H2BodyLengthResult:
    """Per-H2 body length validator (Step 6.7).

    Retries once per under-length H2 group; warns-and-accepts if the
    retry still falls short. Returns the validated article (with retry
    replacements applied), the list of still-under-length H2 sections,
    and retry counters.

    Empty `article` or `min_h2_body_words <= 0` → no-op.
    """
    if not article or min_h2_body_words <= 0:
        return H2BodyLengthResult(validated_article=list(article))

    fn = write_h2_group_fn or write_h2_group

    groups = _collect_h2_groups(article)
    if not groups:
        return H2BodyLengthResult(validated_article=list(article))

    # Build lookup tables: order -> heading_structure dict, so we can
    # rebuild the (h2_item, h3_items) tuple for the retry call without
    # re-deriving from the article output.
    structure_by_order: dict[int, dict] = {}
    for h in heading_structure:
        if isinstance(h, dict) and isinstance(h.get("order"), int):
            structure_by_order[h["order"]] = h


    def _lookup(order: int, expected_level: str) -> Optional[dict]:
        """Phase 3 review fix #4 — guard against `order` collisions.
        Brief assembly assigns unique sequential `order` values, but a
        defensive level check guarantees we never pair an H2 with an
        H3-keyed dict (or vice-versa) under last-wins dict semantics.
        Returns None when the dict's level disagrees with the expected.
        """
        item = structure_by_order.get(order)
        if item is None:
            return None
        if item.get("level") != expected_level:
            logger.warning(
                "writer.h2_length.level_mismatch",
                extra={
                    "order": order,
                    "expected_level": expected_level,
                    "got_level": item.get("level"),
                },
            )
            return None
        return item

    result = H2BodyLengthResult(validated_article=list(article))
    under_length: list[dict] = []
    retries_attempted = 0
    retries_succeeded = 0

    for group in groups:
        sections_in_group: list[ArticleSection] = (
            [group.h2_section] + [s for _, s in group.children]
        )
        group_words = _group_word_count(sections_in_group)
        if group_words >= min_h2_body_words:
            continue

        h2_order = group.h2_section.order
        h2_item = _lookup(h2_order, "H2")
        if h2_item is None:
            # No corresponding H2 entry in heading_structure (or order
            # collided with a non-H2 dict). Can't drive a retry safely.
            logger.warning(
                "writer.h2_length.no_brief_heading",
                extra={"h2_order": h2_order, "h2_text": group.h2_section.heading},
            )
            under_length.append({
                "section_order": h2_order,
                "word_count": group_words,
                "floor": min_h2_body_words,
            })
            continue

        h3_items: list[dict] = []
        children_lookup_failed = False
        for _, child in group.children:
            child_struct = _lookup(child.order, "H3")
            if child_struct is not None:
                h3_items.append(child_struct)
            else:
                children_lookup_failed = True

        # Phase 3 review fix #1 — refusing the retry when any child
        # lookup failed is the safest correctness guarantee. A retry
        # with fewer h3_items than original children would produce a
        # section-count mismatch downstream and trigger our splice
        # guard anyway; bailing here makes the intent explicit and
        # avoids a wasted LLM call.
        if children_lookup_failed:
            under_length.append({
                "section_order": h2_order,
                "word_count": group_words,
                "floor": min_h2_body_words,
            })
            continue

        retries_attempted += 1
        directive = _retry_directive(group_words, min_h2_body_words)
        logger.info(
            "writer.h2_length.retry",
            extra={
                "h2_order": h2_order,
                "h2_text": (group.h2_section.heading or "")[:120],
                "current_words": group_words,
                "floor": min_h2_body_words,
            },
        )
        try:
            retry_result = await fn(
                keyword=keyword,
                intent=intent,
                h2_item=h2_item,
                h3_items=h3_items,
                section_budgets=section_budgets,
                filtered_terms=filtered_terms,
                citations=citations,
                brand_voice_card=brand_voice_card,
                banned_regex=banned_regex,
                length_retry_directive=directive,
                placement_directive=(
                    placement_plan.for_order(h2_order) if placement_plan else None
                ),
            )
        except Exception as exc:
            logger.warning(
                "writer.h2_length.retry_failed",
                extra={
                    "h2_order": h2_order,
                    "error": str(exc),
                },
            )
            under_length.append({
                "section_order": h2_order,
                "word_count": group_words,
                "floor": min_h2_body_words,
            })
            continue

        retry_word_count = sum(_word_count(s.body) for s in retry_result.sections)

        # Phase 3 review fix #1 — guard against section-count mismatch.
        # The contract is "1 H2 + N H3s in → 1 H2 + N H3s out". If the
        # retry returns a different count (LLM merged H3 content into
        # the parent body, or a defensive child-lookup miss meant we
        # passed fewer h3_items into the retry call), splicing the
        # retry sections in would silently DROP H3 sections from the
        # original article. Refuse the splice and flag as under-length.
        expected_count = 1 + len(group.children)
        retry_section_count = len(retry_result.sections)
        if retry_section_count != expected_count:
            logger.warning(
                "writer.h2_length.retry_section_count_mismatch",
                extra={
                    "h2_order": h2_order,
                    "expected": expected_count,
                    "got": retry_section_count,
                    "fallback": "keep_original_sections",
                },
            )
            under_length.append({
                "section_order": h2_order,
                "word_count": group_words,
                "floor": min_h2_body_words,
            })
            continue

        if retry_word_count >= min_h2_body_words:
            retries_succeeded += 1
            result.validated_article = _replace_group_in_article(
                result.validated_article, group, retry_result.sections,
            )
            logger.info(
                "writer.h2_length.retry_succeeded",
                extra={
                    "h2_order": h2_order,
                    "before": group_words,
                    "after": retry_word_count,
                    "floor": min_h2_body_words,
                },
            )
            continue

        # Retry still under — accept whichever attempt has more words.
        if retry_word_count > group_words:
            result.validated_article = _replace_group_in_article(
                result.validated_article, group, retry_result.sections,
            )
            final_words = retry_word_count
        else:
            final_words = group_words

        under_length.append({
            "section_order": h2_order,
            "word_count": final_words,
            "floor": min_h2_body_words,
        })
        logger.warning(
            "writer.h2_length.retry_still_under",
            extra={
                "h2_order": h2_order,
                "final_words": final_words,
                "floor": min_h2_body_words,
            },
        )

    result.under_length_h2_sections = under_length
    result.retries_attempted = retries_attempted
    result.retries_succeeded = retries_succeeded
    logger.info(
        "writer.h2_length.complete",
        extra={
            "groups_inspected": len(groups),
            "retries_attempted": retries_attempted,
            "retries_succeeded": retries_succeeded,
            "under_length_after_retry": len(under_length),
            "floor": min_h2_body_words,
        },
    )
    return result
