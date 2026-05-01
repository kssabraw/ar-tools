"""Module 13 — Recommendation scoring engine.

Inputs (per spec):
- semantic_similarity (0.25)
- tfidf_distinctiveness (0.10)
- pages_found (0.25)
- zone_importance (0.20)
- rank (0.10)
- intent_alignment (0.10)

All inputs min-max normalized across the candidate set before weighting.
Quadgrams in title/H1/H2/H3 receive a multiplicative zone boost.
Dual-signal terms (ngram_and_entity) receive a 1.15x final score multiplier.
"""

from __future__ import annotations

import logging
from typing import Optional

from .ngrams import TermAggregate

logger = logging.getLogger(__name__)


SCORING_WEIGHTS = {
    "semantic_similarity": 0.25,
    "tfidf_distinctiveness": 0.10,
    "pages_found": 0.25,
    "zone_importance": 0.20,
    "rank": 0.10,
    "intent_alignment": 0.10,
}

ZONE_IMPORTANCE_WEIGHTS = {
    "title": 4.0,
    "h1": 3.5,
    "h2": 3.0,
    "h3": 2.0,
    "h4": 1.5,
    "meta_description": 2.5,
    "lists": 1.5,
    "tables": 1.2,
    "faq_blocks": 2.0,
    "paragraphs": 1.0,
}


def _min_max(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _zone_importance(agg: TermAggregate) -> float:
    """Weighted sum of zone counts; higher when present in title/H1/H2."""
    total = 0.0
    for zone, count in agg.zone_counts.items():
        total += ZONE_IMPORTANCE_WEIGHTS.get(zone, 1.0) * count
    return total


def _rank_signal(agg: TermAggregate, rank_by_url: dict[str, int]) -> float:
    """Lower rank == higher signal. Use the best (lowest) rank among source URLs."""
    ranks = [rank_by_url.get(u, 99) for u in agg.source_urls]
    best = min(ranks) if ranks else 99
    return max(0.0, (21 - best) / 20.0)


def _intent_alignment(
    agg: TermAggregate,
    page_categories_by_url: dict[str, str],
    dominant_category: str,
) -> float:
    """Approximate intent alignment from page-category distribution."""
    if not dominant_category:
        return 0.5
    matching = sum(
        1
        for u in agg.source_urls
        if page_categories_by_url.get(u) == dominant_category
    )
    return matching / max(agg.pages_found, 1)


def _quadgram_zone_multiplier(agg: TermAggregate) -> tuple[float, Optional[str]]:
    if agg.n_gram_length != 4:
        return (1.0, None)
    title_pages = len(agg.zone_pages.get("title", set()))
    h1_pages = len(agg.zone_pages.get("h1", set()))
    h2_pages = len(agg.zone_pages.get("h2", set()))
    h3_pages = len(agg.zone_pages.get("h3", set()))
    if title_pages >= 2 or h1_pages >= 2:
        return (1.5, "Found in title/H1 on 2+ pages")
    if h2_pages >= 2:
        return (1.4, "Found in H2 on 2+ pages")
    if h3_pages >= 2:
        return (1.2, "Found in H3 on 2+ pages")
    return (1.0, None)


def score_terms(
    aggregates: dict[str, TermAggregate],
    semantic_scores: dict[str, float],
    tfidf_scores: dict[str, float],
    rank_by_url: dict[str, int],
    page_categories_by_url: dict[str, str],
    dominant_category: str,
    entity_meta: dict[str, dict],
) -> dict[str, dict]:
    """Score each surviving term. Returns term -> {score, type, confidence, reason, ...}."""
    candidates = list(aggregates.values())
    if not candidates:
        return {}

    semantic_norm = _min_max([semantic_scores.get(c.term, 0.0) for c in candidates])
    tfidf_norm = _min_max([tfidf_scores.get(c.term, 0.0) for c in candidates])
    pages_norm = _min_max([float(c.pages_found) for c in candidates])
    zone_norm = _min_max([_zone_importance(c) for c in candidates])
    rank_norm = _min_max([_rank_signal(c, rank_by_url) for c in candidates])
    intent_norm = _min_max([
        _intent_alignment(c, page_categories_by_url, dominant_category)
        for c in candidates
    ])

    out: dict[str, dict] = {}
    for i, c in enumerate(candidates):
        base = (
            SCORING_WEIGHTS["semantic_similarity"] * semantic_norm[i]
            + SCORING_WEIGHTS["tfidf_distinctiveness"] * tfidf_norm[i]
            + SCORING_WEIGHTS["pages_found"] * pages_norm[i]
            + SCORING_WEIGHTS["zone_importance"] * zone_norm[i]
            + SCORING_WEIGHTS["rank"] * rank_norm[i]
            + SCORING_WEIGHTS["intent_alignment"] * intent_norm[i]
        )

        zone_mult, zone_reason = _quadgram_zone_multiplier(c)
        score = base * zone_mult

        meta = entity_meta.get(c.term, {})
        if meta.get("source") == "ngram_and_entity":
            score *= 1.15

        score = min(score, 1.0)

        # Confidence
        if score >= 0.7 and c.pages_found >= 4:
            confidence = "high"
        elif score >= 0.45 or c.pages_found >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        # Recommendation type
        rec_type = "primary_supporting_term"
        if c.template_boilerplate:
            rec_type = "boilerplate_term"
        elif meta.get("source") == "entity_only":
            rec_type = "entity_candidate"
        elif meta.get("entity_category") == "brands":
            rec_type = "brand_specific_term"
        elif meta.get("entity_category") == "locations":
            rec_type = "location_specific_term"
        elif zone_mult > 1.0:
            rec_type = "primary_supporting_term"
        elif c.pages_found < 3:
            rec_type = "secondary_supporting_term"

        # Recommendation category
        if c.template_boilerplate:
            category = "avoid"
            confidence = "high"
            reason = "Detected as template boilerplate (CV < 0.1 across 4+ pages)."
        else:
            category = "required"
            reason = (
                f"Found across {c.pages_found} pages "
                f"(semantic={semantic_scores.get(c.term, 0.0):.2f}, "
                f"tfidf={tfidf_scores.get(c.term, 0.0):.4f})."
            )
            if zone_reason:
                reason += f" {zone_reason} (zone multiplier {zone_mult}x)."

        out[c.term] = {
            "score": round(score, 4),
            "category": category,
            "type": rec_type,
            "confidence": confidence,
            "reason": reason,
            "zone_boost_applied": zone_mult > 1.0,
            "zone_boost_reason": zone_reason,
        }

    return out
