"""Step 4F.1 / Citation Coverage Validator (Writer PRD §4F.1, R7 + Phase 4).

Position in the pipeline:
  Runs AFTER:
    - Step 4 section writing
    - Step 5 FAQ writing
    - Step 6 conclusion writing
    - Step 6.7 H2 body length validator (Phase 3)
  Runs BEFORE:
    - Step 7 citation usage reconciliation

Algorithm:
  For each H2 SECTION GROUP (parent H2 + child H3 bodies):
    1. Detect citable claims via citation_coverage.coverage_for_body.
       Use the SIE Required-term entity list for C6 sentence detection.
    2. If coverage_ratio >= 0.50: pass.
    3. Otherwise: re-run write_h2_group ONCE with a coverage-retry
       directive listing the uncited claims and asking the LLM to
       add markers or rewrite to remove the specific claim.
    4. After retry, recompute coverage.
       - If now >= 50%: succeeded, replace original sections.
       - If still under: apply auto-soften pass on the BODY of every
         section in the group. Auto-soften only touches C7-C9
         operational claims (durations / frequencies / operational
         percentages). Append a record to `under_cited_sections` and
         `operational_claims_softened` for review.

Retry policy mirrors Step 6.7 (warn-and-accept; never abort).

Inputs:
  - article: list[ArticleSection]
  - brief heading_structure (so the retry can rebuild h2_item / h3_items)
  - SIE entity list (for C6 detection)
  - The same per-section dependencies write_h2_group needs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Optional

from models.writer import ArticleSection, BrandVoiceCard

from .citation_coverage import (
    SectionCoverage,
    SoftenReplacement,
    apply_soften,
    coverage_for_body,
    coverage_retry_directive,
)
from .h2_body_length import _H2Group, _collect_h2_groups, _replace_group_in_article
from .brand_placement import BrandPlacementPlan
from .reconciliation import FilteredSIETerms
from .sections import SectionWriteResult, write_h2_group

logger = logging.getLogger(__name__)


COVERAGE_THRESHOLD = 0.50


WriteH2GroupFn = Callable[..., Awaitable[SectionWriteResult]]


@dataclass
class CoverageValidationResult:
    """Output of `validate_citation_coverage`."""

    validated_article: list[ArticleSection] = field(default_factory=list)
    under_cited_sections: list[dict] = field(default_factory=list)
    operational_claims_softened: list[dict] = field(default_factory=list)
    retries_attempted: int = 0
    retries_succeeded: int = 0
    sections_softened: int = 0


def _group_coverage(
    group_sections: list[ArticleSection],
    *,
    entities: Iterable[str],
) -> SectionCoverage:
    """Aggregate coverage across an H2 section group (parent + H3s)."""
    citable = 0
    cited = 0
    matches = []
    for sec in group_sections:
        sub = coverage_for_body(sec.body, entities=entities)
        citable += sub.citable_claims
        cited += sub.cited_claims
        matches.extend(sub.matches)
    return SectionCoverage(citable_claims=citable, cited_claims=cited, matches=matches)


def _extract_entities(filtered_terms: FilteredSIETerms) -> list[str]:
    """Pull entity terms from SIE Required terms (`is_entity == True`).
    The reconciliation DTO doesn't carry the entity flag explicitly —
    we conservatively include every required term so C6 fires on any
    of them."""
    out: list[str] = []
    for t in filtered_terms.required:
        term = getattr(t, "term", "") or ""
        if term:
            out.append(term)
    return out


def _apply_soften_to_group(
    sections: list[ArticleSection],
    h2_order: int,
) -> tuple[list[ArticleSection], list[dict]]:
    """Run apply_soften over each section's body. Returns the
    (possibly mutated) sections and the per-section softening records."""
    new_sections: list[ArticleSection] = []
    records: list[dict] = []
    for sec in sections:
        softened_body, replacements = apply_soften(sec.body)
        if replacements:
            updated = sec.model_copy(update={
                "body": softened_body,
                "word_count": len(softened_body.split()) if softened_body else 0,
            })
            records.extend({
                "section_order": sec.order,
                "h2_order": h2_order,
                "rule": r.rule,
                "original": r.original,
                "softened": r.softened,
            } for r in replacements)
            new_sections.append(updated)
        else:
            new_sections.append(sec)
    return new_sections, records


async def validate_citation_coverage(
    article: list[ArticleSection],
    *,
    keyword: str,
    intent: str,
    heading_structure: list[dict],
    section_budgets: dict[int, int],
    filtered_terms: FilteredSIETerms,
    citations: list[dict],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    threshold: float = COVERAGE_THRESHOLD,
    placement_plan: Optional[BrandPlacementPlan] = None,
    write_h2_group_fn: Optional[WriteH2GroupFn] = None,
) -> CoverageValidationResult:
    """Step 4F.1 — per-H2 citable-claim detection + coverage retry +
    auto-soften fallback.

    Empty `article` or `threshold <= 0` → no-op.
    """
    if not article or threshold <= 0:
        return CoverageValidationResult(validated_article=list(article))

    fn = write_h2_group_fn or write_h2_group

    groups = _collect_h2_groups(article)
    if not groups:
        return CoverageValidationResult(validated_article=list(article))

    structure_by_order: dict[int, dict] = {}
    for h in heading_structure:
        if isinstance(h, dict) and isinstance(h.get("order"), int):
            structure_by_order[h["order"]] = h

    def _lookup(order: int, expected_level: str) -> Optional[dict]:
        item = structure_by_order.get(order)
        if item is None or item.get("level") != expected_level:
            return None
        return item

    available_citation_ids = sorted({
        (c.get("citation_id") or "")
        for c in citations
        if isinstance(c, dict) and c.get("citation_id")
    })

    entities = _extract_entities(filtered_terms)

    result = CoverageValidationResult(validated_article=list(article))
    under_cited: list[dict] = []
    softened_records: list[dict] = []
    retries_attempted = 0
    retries_succeeded = 0
    sections_softened = 0

    for group in groups:
        sections_in_group: list[ArticleSection] = (
            [group.h2_section] + [s for _, s in group.children]
        )
        coverage = _group_coverage(sections_in_group, entities=entities)
        if coverage.citable_claims == 0:
            continue
        if coverage.ratio >= threshold:
            continue

        h2_order = group.h2_section.order
        h2_item = _lookup(h2_order, "H2")
        if h2_item is None:
            # Defensive — flag without retrying.
            under_cited.append({
                "section_order": h2_order,
                "citable_claims": coverage.citable_claims,
                "cited_claims": coverage.cited_claims,
                "ratio": round(coverage.ratio, 3),
                "threshold": threshold,
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

        if children_lookup_failed:
            # Same guard as Step 6.7 — refuse retry rather than dropping
            # H3 sections via section-count mismatch downstream.
            under_cited.append({
                "section_order": h2_order,
                "citable_claims": coverage.citable_claims,
                "cited_claims": coverage.cited_claims,
                "ratio": round(coverage.ratio, 3),
                "threshold": threshold,
            })
            continue

        retries_attempted += 1
        directive = coverage_retry_directive(
            coverage, available_citation_ids, threshold=threshold,
        )
        logger.info(
            "writer.coverage.retry",
            extra={
                "h2_order": h2_order,
                "h2_text": (group.h2_section.heading or "")[:120],
                "citable": coverage.citable_claims,
                "cited": coverage.cited_claims,
                "ratio": round(coverage.ratio, 3),
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
                coverage_retry_directive=directive,
                placement_directive=(
                    placement_plan.for_order(h2_order) if placement_plan else None
                ),
            )
        except Exception as exc:
            logger.warning(
                "writer.coverage.retry_failed",
                extra={"h2_order": h2_order, "error": str(exc)},
            )
            # Fall through to soften pass on original sections.
            retry_result = None

        # Same section-count guard as Step 6.7 fix #1 — refuse splice
        # if the retry returned the wrong number of sections.
        expected_count = 1 + len(group.children)
        if (
            retry_result is not None
            and len(retry_result.sections) == expected_count
        ):
            new_coverage = _group_coverage(
                retry_result.sections, entities=entities,
            )
            if new_coverage.ratio >= threshold:
                retries_succeeded += 1
                result.validated_article = _replace_group_in_article(
                    result.validated_article, group, retry_result.sections,
                )
                logger.info(
                    "writer.coverage.retry_succeeded",
                    extra={
                        "h2_order": h2_order,
                        "before_ratio": round(coverage.ratio, 3),
                        "after_ratio": round(new_coverage.ratio, 3),
                    },
                )
                continue
            # Retry didn't clear; fall through with the retry's sections
            # so soften acts on the more recent (likely better) text.
            current_sections = retry_result.sections
            current_coverage = new_coverage
            result.validated_article = _replace_group_in_article(
                result.validated_article, group, retry_result.sections,
            )
        else:
            if retry_result is not None:
                logger.warning(
                    "writer.coverage.retry_section_count_mismatch",
                    extra={
                        "h2_order": h2_order,
                        "expected": expected_count,
                        "got": len(retry_result.sections),
                    },
                )
            current_sections = sections_in_group
            current_coverage = coverage

        # Auto-soften fallback — Phase 4. Only operational claims (C7-C9)
        # are softened; C1-C6 statistics/years stay flagged.
        softened_sections, replacements = _apply_soften_to_group(
            current_sections, h2_order=h2_order,
        )
        if replacements:
            sections_softened += 1
            softened_records.extend(replacements)
            # Splice softened sections back in. Group's h2_index in
            # `result.validated_article` may have shifted if a previous
            # iteration modified the list — rebuild groups isn't worth
            # it here; the splice helper indexes by group structure
            # which we still hold.
            result.validated_article = _replace_group_in_article(
                result.validated_article, group, softened_sections,
            )

        under_cited.append({
            "section_order": h2_order,
            "citable_claims": current_coverage.citable_claims,
            "cited_claims": current_coverage.cited_claims,
            "ratio": round(current_coverage.ratio, 3),
            "threshold": threshold,
            "operational_claims_softened": len(replacements),
        })
        logger.warning(
            "writer.coverage.under_cited_after_retry",
            extra={
                "h2_order": h2_order,
                "ratio": round(current_coverage.ratio, 3),
                "softened_claims": len(replacements),
            },
        )

    result.under_cited_sections = under_cited
    result.operational_claims_softened = softened_records
    result.retries_attempted = retries_attempted
    result.retries_succeeded = retries_succeeded
    result.sections_softened = sections_softened
    logger.info(
        "writer.coverage.complete",
        extra={
            "groups_inspected": len(groups),
            "retries_attempted": retries_attempted,
            "retries_succeeded": retries_succeeded,
            "sections_softened": sections_softened,
            "under_cited_after_retry": len(under_cited),
            "threshold": threshold,
        },
    )
    return result
