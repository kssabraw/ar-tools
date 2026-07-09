"""Term-coverage enforcement - SIE targets vs what the article delivered.

The SIE supplies required terms with per-zone targets and the writer's
prompts request them, but until this module nothing ever compared the
finished article against the targets. Owner spec (2026-07-09):

- **Quadgrams** - the corpus-derived 4-word phrases in the SIE required
  pool (the SIE generates 1-4-grams from the competitor corpus; the
  4-grams that survive scoring arrive here as required terms). The top
  `writer_quadgram_track_max` are tracked: each must appear at least
  once in the article. Any required term used more than
  `writer_term_occurrence_cap` times flags as keyword stuffing.
- **Entities** - if EITHER bar falls below `writer_entity_coverage_min`
  (0.75): unique coverage (share of supplied entities used at least
  once) or total coverage (entity occurrences vs the summed SIE
  targets), the article gets ONE auto-rewrite pass: the content H2
  groups using the fewest entities are regenerated with a directive
  naming the missing terms (missed quadgrams ride along). Still short
  after the retry → flagged on the run-detail QA panel. Same
  warn-and-accept pattern as the word-floor / citation-coverage
  validators; never aborts.

The coverage computation is pure and deterministic - no LLM call. The
rewrite reuses `write_h2_group` plus the word-floor validator's group
collection / splice guards.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from config import settings
from models.writer import ArticleSection, BrandVoiceCard

from .brand_placement import BrandPlacementPlan
from .h2_body_length import _collect_h2_groups, _replace_group_in_article
from .reconciliation import FilteredSIETerms, ReconciledTerm
from .sections import SectionWriteResult, write_h2_group

logger = logging.getLogger(__name__)


_MARKER_RE = re.compile(r"\{\{cit_\d+\}\}")


@dataclass
class TermCoverageStats:
    """Pure comparison of SIE required terms vs article usage."""

    # Quadgram rule (min 1 use each for the tracked corpus 4-grams).
    quadgrams_tracked: list[str] = field(default_factory=list)
    quadgrams_missing: list[str] = field(default_factory=list)
    # Stuffing cap - any required term above `writer_term_occurrence_cap`.
    terms_over_cap: list[dict] = field(default_factory=list)
    # Entity bars. Percentages are None when SIE supplied no entities
    # (or, for total, no positive targets) - unknown, not zero.
    entities_supplied: int = 0
    entities_used: int = 0
    entity_unique_coverage_pct: Optional[float] = None
    entity_total_target: int = 0
    entity_total_used: int = 0
    entity_total_coverage_pct: Optional[float] = None
    entities_missing: list[str] = field(default_factory=list)
    # True when EITHER bar sits below the 0.75 threshold (owner spec).
    entity_rewrite_triggered: bool = False


@dataclass
class TermCoverageResult:
    validated_article: list[ArticleSection]
    stats: TermCoverageStats
    sections_retried: int = 0
    # None = no rewrite ran; True = coverage cleared after the retry;
    # False = still below the bar (flag for review).
    rewrite_resolved: Optional[bool] = None


def _term_pattern(term: str) -> Optional[re.Pattern]:
    tokens = [t for t in term.lower().split() if t]
    if not tokens:
        return None
    return re.compile(r"\b" + r"\s+".join(re.escape(t) for t in tokens) + r"\b")


def _article_text(article: list[ArticleSection]) -> str:
    parts: list[str] = []
    for s in article:
        if s.heading:
            parts.append(s.heading)
        if s.body:
            parts.append(_MARKER_RE.sub("", s.body))
    return "\n".join(parts).lower()


def _count(term: str, text_lower: str) -> int:
    pattern = _term_pattern(term)
    return len(pattern.findall(text_lower)) if pattern else 0


def _is_quadgram(term: ReconciledTerm) -> bool:
    """Corpus quadgram = a 4-token required term that isn't an entity
    (entities are governed by the 75% bars, not the min-1 rule)."""
    return not term.is_entity and len(term.term.split()) == 4


def compute_term_coverage(
    article: list[ArticleSection],
    filtered_terms: FilteredSIETerms,
    *,
    quadgram_track_max: Optional[int] = None,
    occurrence_cap: Optional[int] = None,
    entity_min: Optional[float] = None,
) -> TermCoverageStats:
    """Pure, deterministic coverage computation. No LLM, no I/O."""
    track_max = quadgram_track_max if quadgram_track_max is not None else settings.writer_quadgram_track_max
    cap = occurrence_cap if occurrence_cap is not None else settings.writer_term_occurrence_cap
    min_pct = entity_min if entity_min is not None else settings.writer_entity_coverage_min

    stats = TermCoverageStats()
    required = filtered_terms.required or []
    if not article or not required:
        return stats

    text = _article_text(article)
    counts: dict[str, int] = {t.term: _count(t.term, text) for t in required}

    # ---- Quadgram rule: min 1 each for the top-N corpus 4-grams ----
    # `required` arrives in SIE composite-score order, so "top N" is
    # simply the first N quadgrams encountered.
    tracked = [t.term for t in required if _is_quadgram(t)][:track_max]
    stats.quadgrams_tracked = tracked
    stats.quadgrams_missing = [q for q in tracked if counts.get(q, 0) == 0]

    # ---- Stuffing cap: no required term above the occurrence cap ----
    stats.terms_over_cap = [
        {"term": term, "count": n, "cap": cap}
        for term, n in counts.items()
        if n > cap
    ]

    # ---- Entity bars (owner spec: EITHER below 0.75 triggers) ----
    entities = [t for t in required if t.is_entity]
    stats.entities_supplied = len(entities)
    if entities:
        used = [t for t in entities if counts.get(t.term, 0) > 0]
        stats.entities_used = len(used)
        stats.entity_unique_coverage_pct = round(len(used) / len(entities), 3)
        stats.entities_missing = [
            t.term for t in entities if counts.get(t.term, 0) == 0
        ]
        target_sum = sum(max(t.effective_target, 0) for t in entities)
        stats.entity_total_target = target_sum
        stats.entity_total_used = sum(counts.get(t.term, 0) for t in entities)
        if target_sum > 0:
            stats.entity_total_coverage_pct = round(
                min(stats.entity_total_used / target_sum, 1.0), 3
            )
        unique_short = stats.entity_unique_coverage_pct < min_pct
        total_short = (
            stats.entity_total_coverage_pct is not None
            and stats.entity_total_coverage_pct < min_pct
        )
        stats.entity_rewrite_triggered = unique_short or total_short
    return stats


def _rewrite_directive(stats: TermCoverageStats) -> str:
    lines = [
        "ENTITY COVERAGE RETRY: A previous attempt under-used the required "
        "entities article-wide. This section must work the following terms "
        "in naturally (each at least once in this section; keep the prose "
        "publication-ready, never a keyword list):",
    ]
    for term in stats.entities_missing[:12]:
        lines.append(f"  - {term}")
    if stats.quadgrams_missing:
        lines.append(
            "Also weave in these exact phrases where natural (each at least "
            "once):"
        )
        for q in stats.quadgrams_missing[:5]:
            lines.append(f"  - {q}")
    return "\n".join(lines)


WriteH2GroupFn = Callable[..., Awaitable[SectionWriteResult]]


async def enforce_term_coverage(
    article: list[ArticleSection],
    *,
    keyword: str,
    intent: str,
    h2_groups: list[tuple[dict, list[dict]]],
    section_budgets: dict[int, int],
    filtered_terms: FilteredSIETerms,
    citations: list[dict],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    placement_plan: Optional[BrandPlacementPlan] = None,
    write_h2_group_fn: Optional[WriteH2GroupFn] = None,
) -> TermCoverageResult:
    """Compute coverage; on an entity-bar failure rewrite the weakest
    sections once and re-measure. Never raises past the LLM call guard.

    `h2_groups` is the SAME (h2_item, h3_items) list the section loop
    wrote from. The article's content H2 groups correspond to it 1:1 by
    POSITION - matching positionally instead of by `order` matters
    because the pipeline resequences section orders (1..N by final list
    position) before the validators run, so section orders no longer
    agree with the brief structure's orders."""
    stats = compute_term_coverage(article, filtered_terms)
    result = TermCoverageResult(validated_article=list(article), stats=stats)
    if not settings.writer_term_coverage_enabled:
        return TermCoverageResult(validated_article=list(article), stats=TermCoverageStats())
    if not stats.entity_rewrite_triggered or not settings.writer_entity_rewrite_enabled:
        return result

    fn = write_h2_group_fn or write_h2_group
    article_groups = _collect_h2_groups(result.validated_article)
    if len(article_groups) != len(h2_groups):
        # Positional alignment broken (shouldn't happen - splice guards
        # keep group counts stable). Refuse the rewrite; flag only.
        logger.warning(
            "writer.term_coverage.group_count_mismatch",
            extra={"article_groups": len(article_groups), "brief_groups": len(h2_groups)},
        )
        result.rewrite_resolved = False
        return result

    # Weakest first: the content H2 groups using the fewest entity
    # occurrences have the most room to absorb the missing terms.
    entity_terms = [t for t in (filtered_terms.required or []) if t.is_entity]

    def _group_entity_count(pair) -> int:
        group = pair[0]
        text = _article_text([group.h2_section] + [s for _, s in group.children])
        return sum(_count(t.term, text) for t in entity_terms)

    pairs = list(zip(article_groups, h2_groups))
    ranked = sorted(pairs, key=_group_entity_count)
    directive = _rewrite_directive(stats)
    max_sections = settings.writer_entity_rewrite_max_sections

    retried = 0
    for group, (h2_item, h3_items) in ranked[:max_sections]:
        if len(group.children) != len(h3_items):
            logger.warning(
                "writer.term_coverage.child_count_mismatch",
                extra={"h2_text": (h2_item.get("text") or "")[:120]},
            )
            continue

        try:
            retry = await fn(
                keyword=keyword,
                intent=intent,
                h2_item=h2_item,
                h3_items=h3_items,
                section_budgets=section_budgets,
                filtered_terms=filtered_terms,
                citations=citations,
                brand_voice_card=brand_voice_card,
                banned_regex=banned_regex,
                term_retry_directive=directive,
                placement_directive=(
                    placement_plan.for_order(h2_item.get("order", -1))
                    if placement_plan else None
                ),
            )
        except Exception as exc:
            logger.warning(
                "writer.term_coverage.retry_failed",
                extra={"h2_text": (h2_item.get("text") or "")[:120], "error": str(exc)},
            )
            continue
        # Same splice guard as the word-floor validator: a section-count
        # mismatch would silently drop H3s - keep the originals instead.
        if len(retry.sections) != 1 + len(group.children):
            logger.warning(
                "writer.term_coverage.retry_section_count_mismatch",
                extra={"h2_text": (h2_item.get("text") or "")[:120]},
            )
            continue
        # Retry sections carry the BRIEF's order values; the article was
        # resequenced (1..N). Re-stamp with the outgoing sections' orders
        # so the renderer's order-sort keeps them in place.
        old_sections = [group.h2_section] + [s for _, s in group.children]
        for new_section, old_section in zip(retry.sections, old_sections):
            new_section.order = old_section.order
        result.validated_article = _replace_group_in_article(
            result.validated_article, group, retry.sections,
        )
        retried += 1

    result.sections_retried = retried
    if retried:
        result.stats = compute_term_coverage(result.validated_article, filtered_terms)
        result.rewrite_resolved = not result.stats.entity_rewrite_triggered
        # Preserve the fact that a rewrite ran even when it cleared the bar.
        result.stats.entity_rewrite_triggered = True
        logger.info(
            "writer.term_coverage.rewrite_done",
            extra={
                "sections_retried": retried,
                "resolved": result.rewrite_resolved,
                "unique_pct": result.stats.entity_unique_coverage_pct,
                "total_pct": result.stats.entity_total_coverage_pct,
            },
        )
    else:
        result.rewrite_resolved = False
    return result
