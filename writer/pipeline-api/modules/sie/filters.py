"""Modules 9 + 10 — TF-IDF pre-filter and semantic similarity filter."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from modules.brief.llm import cosine, embed_batch

from .ngrams import TermAggregate
from .zones import PageZones

logger = logging.getLogger(__name__)

DEFAULT_TFIDF_THRESHOLD = 0.005
DEFAULT_SEMANTIC_THRESHOLD = 0.65
SEMANTIC_LOWER_BOUND = 0.60
SEMANTIC_UPPER_BOUND = 0.70


def compute_tfidf(
    aggregates: dict[str, TermAggregate],
    pages: list[PageZones],
    threshold: float = DEFAULT_TFIDF_THRESHOLD,
) -> tuple[dict[str, float], int]:
    """Compute corpus-level TF-IDF for each term.

    Returns (term -> corpus_tfidf_score, count_filtered).
    Mutates each TermAggregate's flags via passes_coverage_threshold not changed
    here — TF-IDF is a separate filter applied during scoring.
    """
    n_pages = len(pages)
    if n_pages == 0:
        return ({}, 0)

    page_word_counts = {p.url: max(p.word_count, 1) for p in pages}
    scores: dict[str, float] = {}

    for term, agg in aggregates.items():
        if agg.pages_found == 0:
            continue
        idf = math.log(n_pages / agg.pages_found) if agg.pages_found > 0 else 0.0
        # Per-page TF, then average
        per_page_tfidf = []
        for url, count in agg.per_page_count.items():
            tf = count / page_word_counts.get(url, 1)
            per_page_tfidf.append(tf * idf)
        if per_page_tfidf:
            scores[term] = sum(per_page_tfidf) / len(per_page_tfidf)

    filtered = sum(1 for s in scores.values() if s < threshold)
    return (scores, filtered)


def passes_tfidf(
    agg: TermAggregate,
    score: float,
    threshold: float = DEFAULT_TFIDF_THRESHOLD,
) -> bool:
    """Coverage exceptions / zone-protected terms always pass TF-IDF gate."""
    if agg.coverage_exception:
        return True
    # Zone-protection: title/H1/H2 on 2+ pages
    for zone in ("title", "h1", "h2"):
        if len(agg.zone_pages.get(zone, set())) >= 2:
            return True
    return score >= threshold


async def filter_semantic(
    keyword: str,
    aggregates: dict[str, TermAggregate],
    tfidf_scores: dict[str, float],
    base_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> tuple[dict[str, float], float]:
    """Embed terms + keyword, return (term -> similarity, threshold_used).

    Implements dynamic threshold: drops to 0.60 if <25 pass, raises to 0.70
    if >300 pass. Always preserves terms in title/H1/H2 across 3+ pages.
    """
    if not aggregates:
        return ({}, base_threshold)

    # Filter to candidates that survived prior gates (have a TF-IDF score and pass)
    candidates: list[TermAggregate] = []
    for term, agg in aggregates.items():
        if agg.template_boilerplate:
            continue
        if not agg.passes_coverage_threshold:
            continue
        score = tfidf_scores.get(term, 0.0)
        if not passes_tfidf(agg, score):
            continue
        candidates.append(agg)

    if not candidates:
        return ({}, base_threshold)

    texts = [keyword] + [c.term for c in candidates]
    try:
        vectors = await embed_batch(texts)
    except Exception as exc:
        logger.warning("Semantic filter embedding failed: %s", exc)
        return ({}, base_threshold)

    if not vectors:
        return ({}, base_threshold)

    keyword_vec = vectors[0]
    sims: dict[str, float] = {}
    for c, v in zip(candidates, vectors[1:]):
        sims[c.term] = cosine(keyword_vec, v)

    # Dynamic threshold
    above = [t for t, s in sims.items() if s >= base_threshold]
    threshold = base_threshold
    if len(above) < 25:
        threshold = SEMANTIC_LOWER_BOUND
    elif len(above) > 300:
        threshold = SEMANTIC_UPPER_BOUND

    return (sims, threshold)


def is_zone_protected(agg: TermAggregate, min_pages: int = 3) -> bool:
    """Title/H1/H2 across N+ pages should survive semantic filter even if
    similarity is slightly below threshold."""
    for zone in ("title", "h1", "h2"):
        if len(agg.zone_pages.get(zone, set())) >= min_pages:
            return True
    return False
