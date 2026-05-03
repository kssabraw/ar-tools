"""TextRazor entity aggregation + filtering (SIE v1.2).

Mirrors the Google NLP entity flow but with TextRazor's per-occurrence
relevance / confidence semantics. Per the user spec:

  - Per-occurrence filter: relevanceScore >= 0.33 AND confidenceScore >= 2.00
  - Aggregate filter: must appear on > 3 distinct pages (i.e. >= 4)
  - Anything failing either gets discarded here (won't reach scoring)

Result is a list of `AggregatedTextRazorEntity` objects with the same
shape downstream consumers need: name, variants, pages_found,
source_urls, plus aggregated relevance / confidence stats useful for
debugging.

These get merged into the SIE aggregates dict alongside Google NLP
entities by `entities.py:merge_entities_into_terms` (extended in v1.2
to accept TextRazor entities). Once merged they share the same
per-zone usage counting (`usage.py:build_usage`) and scoring
(`scoring.py:score_terms`) as Google NLP entities.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .textrazor_client import PageTextRazorResult, TextRazorEntity

logger = logging.getLogger(__name__)


# Per-occurrence filter thresholds. Per user spec — TextRazor returns
# relevance in [0, 1] and confidence in roughly [0, 10+]. These are
# the floor for an individual occurrence to be counted toward the
# aggregate; an entity that fails either threshold doesn't contribute
# even one page to the per-entity page count.
TEXTRAZOR_MIN_RELEVANCE = 0.33
TEXTRAZOR_MIN_CONFIDENCE = 2.00

# Aggregate filter: minimum distinct page count (after per-occurrence
# filter) for the entity to survive. Spec is "discarded if used on 3
# or fewer pages" — i.e. strictly > 3 (≥ 4). Aligns with the existing
# n-gram coverage gate (≥ 3) but slightly stricter for TextRazor since
# free-tier accuracy on niche entities can be noisy.
TEXTRAZOR_MIN_PAGES = 4


@dataclass
class AggregatedTextRazorEntity:
    """Same shape as `entities.py:AggregatedEntity` (different module
    so we don't tangle the dataclasses, but downstream code can treat
    them interchangeably for merging into the SIE aggregates dict)."""

    name: str
    avg_relevance: float
    max_confidence: float
    pages_found: int
    source_urls: list[str]
    variants: list[str]
    types: list[str] = field(default_factory=list)
    wiki_link: Optional[str] = None


def _normalize_name(name: str) -> str:
    """Lowercase + strip — TextRazor entityIds are already canonical
    (Wikipedia titles), so we don't lemmatize them. Mirrors the
    behavior of `entities._normalize_entity_name` enough to dedup
    cross-source matches downstream."""
    return (name or "").strip().lower()


def aggregate_textrazor_results(
    per_page: list[PageTextRazorResult],
) -> list[AggregatedTextRazorEntity]:
    """Combine per-page TextRazor entities into aggregated records.

    Applies per-occurrence filter (rel ≥ 0.33, conf ≥ 2.00) and the
    aggregate page filter (> 3 pages) per the v1.2 spec. Anything that
    survives gets returned with rolled-up stats.
    """
    by_norm: dict[str, dict] = defaultdict(lambda: {
        "names": [],
        "matched_texts": [],
        "relevances": [],
        "confidences": [],
        "types": set(),
        "wiki_link": None,
        "urls": set(),
    })

    for page in per_page:
        if page.failed:
            continue
        for ent in page.entities:
            # Per-occurrence filter
            if ent.relevance < TEXTRAZOR_MIN_RELEVANCE:
                continue
            if ent.confidence < TEXTRAZOR_MIN_CONFIDENCE:
                continue
            norm = _normalize_name(ent.name)
            if not norm:
                continue
            slot = by_norm[norm]
            slot["names"].append(ent.name)
            slot["matched_texts"].append(ent.matched_text)
            slot["relevances"].append(ent.relevance)
            slot["confidences"].append(ent.confidence)
            slot["types"].update(ent.type)
            if ent.wiki_link and not slot["wiki_link"]:
                slot["wiki_link"] = ent.wiki_link
            slot["urls"].add(page.url)

    aggregated: list[AggregatedTextRazorEntity] = []
    for norm, slot in by_norm.items():
        pages_found = len(slot["urls"])
        if pages_found < TEXTRAZOR_MIN_PAGES:
            # Aggregate filter — discard low-coverage entities.
            continue
        # Most-common original casing wins as the canonical name.
        canonical = Counter(slot["names"]).most_common(1)[0][0]
        variants = sorted(set(slot["matched_texts"]) | set(slot["names"]))
        aggregated.append(AggregatedTextRazorEntity(
            name=canonical,
            avg_relevance=sum(slot["relevances"]) / len(slot["relevances"]),
            max_confidence=max(slot["confidences"]),
            pages_found=pages_found,
            source_urls=sorted(slot["urls"]),
            variants=variants,
            types=sorted(slot["types"]),
            wiki_link=slot["wiki_link"],
        ))

    logger.info(
        "sie.textrazor.aggregated",
        extra={
            "input_pages": len(per_page),
            "successful_pages": sum(1 for p in per_page if not p.failed),
            "candidate_count": len(by_norm),
            "promoted_count": len(aggregated),
            "min_relevance": TEXTRAZOR_MIN_RELEVANCE,
            "min_confidence": TEXTRAZOR_MIN_CONFIDENCE,
            "min_pages": TEXTRAZOR_MIN_PAGES,
        },
    )
    return aggregated
