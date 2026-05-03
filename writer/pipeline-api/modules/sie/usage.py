"""Module 14 — Usage Recommendation Engine.

Per-zone min/target/max counts using percentile-based ranges over per-1000-words
frequency. Supports safe (default) and aggressive outlier modes.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .ngrams import TermAggregate
from .zones import PageZones

logger = logging.getLogger(__name__)


HARD_CAP_PER_1000_WORDS = 10
SAFE_OUTLIER_MULT = 3.0
ZONES = ("title", "h1", "h2", "h3", "paragraphs")

# SIE v1.4 — three-bucket category aggregate, benchmarked at 50% of
# trimmed-max competitor distinct-item count. The 0.50 multiplier is
# the user-spec'd "target half of the most aggressive competitor."
# We use absolute counts (no per-1000 normalization) because category
# coverage in title/h1/h2/h3 zones is structurally bounded by the
# zone's natural length — competitor titles aren't longer because
# their articles are longer.
ZONE_CATEGORY_TARGET_MULT = 0.50

CATEGORY_ENTITIES = "entities"
CATEGORY_RELATED_KEYWORDS = "related_keywords"
CATEGORY_KEYWORD_VARIANTS = "keyword_variants"
CATEGORIES = (
    CATEGORY_ENTITIES,
    CATEGORY_RELATED_KEYWORDS,
    CATEGORY_KEYWORD_VARIANTS,
)


def _per_1000(count: int, word_count: int) -> float:
    if word_count <= 0:
        return 0.0
    return (count / word_count) * 1000


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(values, p))


def _detect_outliers(frequencies: list[float], multiplier: float = SAFE_OUTLIER_MULT) -> list[int]:
    """Return indices of outliers (>= multiplier * median of others)."""
    if len(frequencies) < 3:
        return []
    median = float(np.median(frequencies))
    if median == 0:
        return []
    threshold = median * multiplier
    return [i for i, f in enumerate(frequencies) if f >= threshold]


def _compute_zone_range(
    zone_counts_per_page: dict[str, int],
    page_word_counts: dict[str, int],
    target_word_count: int,
    outlier_mode: str,
) -> tuple[int, int, int, int, Optional[str]]:
    """Returns (min, target, max, outlier_pages_excluded, outlier_url_if_any)."""
    if not zone_counts_per_page:
        return (0, 0, 0, 0, None)

    urls = list(zone_counts_per_page.keys())
    raw_freqs = [
        _per_1000(zone_counts_per_page[u], page_word_counts.get(u, 1))
        for u in urls
    ]

    excluded = 0
    outlier_url: Optional[str] = None
    freqs = list(raw_freqs)
    if outlier_mode == "safe":
        outlier_indices = _detect_outliers(freqs)
        if outlier_indices:
            excluded = len(outlier_indices)
            outlier_url = urls[outlier_indices[0]]
            freqs = [f for i, f in enumerate(freqs) if i not in outlier_indices]

    if not freqs:
        freqs = raw_freqs

    p25 = _percentile(freqs, 25)
    p50 = _percentile(freqs, 50)
    p75 = _percentile(freqs, 75)

    # Convert per-1000 frequency to absolute counts at target word count
    def _to_count(per_1000: float) -> int:
        return max(0, int(round(per_1000 * target_word_count / 1000)))

    return (
        _to_count(p25),
        _to_count(p50),
        _to_count(p75),
        excluded,
        outlier_url,
    )


def build_usage(
    aggregates: dict[str, TermAggregate],
    pages: list[PageZones],
    target_word_count: int,
    outlier_mode: str = "safe",
) -> list[dict]:
    """Build usage recommendations for terms in the aggregates dict.

    Returns list of dicts ready to feed into pydantic UsageRecommendation.
    """
    page_word_counts = {p.url: max(p.word_count, 1) for p in pages}

    # Build per-zone-per-page count map for each term
    zone_count_by_term_and_url: dict[str, dict[str, dict[str, int]]] = {}
    for page in pages:
        zones = page.all_zone_text()
        for zone_name in ZONES:
            blocks = zones.get(zone_name, [])
            if not blocks:
                continue
            joined = " ".join(blocks).lower()
            for term in aggregates.keys():
                if not term:
                    continue
                # Rough count: substring occurrences of the term token sequence
                if " " in term:
                    count = joined.count(term)
                else:
                    # word boundary count
                    import re
                    count = len(re.findall(rf"\b{re.escape(term)}\b", joined))
                if count > 0:
                    zone_count_by_term_and_url.setdefault(term, {}).setdefault(zone_name, {})[page.url] = count

    out: list[dict] = []
    for term in aggregates.keys():
        per_zone = zone_count_by_term_and_url.get(term, {})
        usage_zones: dict[str, dict[str, int]] = {}
        warnings: list[str] = []
        outlier_pages_excluded = 0
        outlier_page_url: Optional[str] = None

        for zone in ZONES:
            counts = per_zone.get(zone, {})
            mn, tg, mx, excluded, outlier_url = _compute_zone_range(
                counts, page_word_counts, target_word_count, outlier_mode,
            )
            if excluded > outlier_pages_excluded:
                outlier_pages_excluded = excluded
                outlier_page_url = outlier_url

            # Hard cap
            cap_count = int(HARD_CAP_PER_1000_WORDS * target_word_count / 1000)
            if mx > cap_count:
                warnings.append(
                    f"{zone}: max {mx} exceeds hard cap of {cap_count} per article"
                )
                mx = cap_count

            usage_zones[zone] = {"min": mn, "target": tg, "max": mx}

        # Aggressive mode warning if p75 > 2x p50 anywhere
        if outlier_mode == "aggressive":
            for zone, cnt in usage_zones.items():
                if cnt["target"] > 0 and cnt["max"] >= 2 * cnt["target"]:
                    warnings.append(
                        f"{zone}: aggressive mode includes outlier pages; "
                        "high-end recommendation may reflect keyword stuffing"
                    )
                    break

        confidence = "high" if aggregates[term].pages_found >= 5 else "medium"
        out.append({
            "term": term,
            "mode": outlier_mode,
            "usage": usage_zones,
            "outlier_pages_excluded": outlier_pages_excluded,
            "outlier_page_url": outlier_page_url,
            "confidence": confidence,
            "warning": "; ".join(warnings) if warnings else None,
        })

    return out


def _classify_term(
    term: str,
    entity_meta: dict[str, dict],
    seed_fragment_terms: set[str],
) -> str:
    """Bucket a term into the v1.4 three-bucket taxonomy.

    Order matters: a term that's BOTH an entity and a seed fragment
    should never happen (mark_seed_keyword_fragments protects entities
    from being flagged), but if upstream invariants break we prefer
    the entity classification — it carries more semantic weight than
    the keyword-echo signal.
    """
    if entity_meta.get(term, {}).get("is_entity"):
        return CATEGORY_ENTITIES
    if term in seed_fragment_terms:
        return CATEGORY_KEYWORD_VARIANTS
    return CATEGORY_RELATED_KEYWORDS


def build_zone_category_targets(
    aggregates: dict[str, TermAggregate],
    pages: list[PageZones],
    entity_meta: dict[str, dict],
    seed_fragment_terms: set[str],
    outlier_mode: str = "safe",
) -> dict[str, dict[str, dict[str, int]]]:
    """SIE v1.4 — per-zone per-category aggregate distinct-item targets.

    For each (zone, category) pair, count distinct items present in
    each competitor page's zone, find the trimmed-max across competitor
    pages, and target = round(trimmed_max × 0.50). Outlier exclusion
    follows the same SAFE_OUTLIER_MULT logic as `_compute_zone_range`
    but operates on per-page distinct counts instead of per-1000-words
    frequencies.

    Returns a dict shaped:
        {zone: {category: {target: int, max: int}}}
    where category ∈ {entities, related_keywords, keyword_variants}
    and zone ∈ ZONES.

    Empty when `aggregates` is empty (no pages to benchmark against).
    """
    # Default-zero scaffold so callers can index without KeyError even
    # when a (zone, category) pair had zero distinct items in every
    # competitor page.
    out: dict[str, dict[str, dict[str, int]]] = {
        z: {c: {"target": 0, "max": 0} for c in CATEGORIES} for z in ZONES
    }
    if not aggregates or not pages:
        return out

    term_to_category = {
        term: _classify_term(term, entity_meta, seed_fragment_terms)
        for term in aggregates.keys() if term
    }

    # For each page, for each zone, count distinct terms per category.
    # Substring/word-boundary search mirrors `build_usage` so the same
    # term-presence semantics drive both per-term and aggregate
    # benchmarks.
    import re as _re

    distinct_counts: dict[str, dict[str, dict[str, int]]] = {
        p.url: {z: {c: 0 for c in CATEGORIES} for z in ZONES} for p in pages
    }
    for page in pages:
        zones_text = page.all_zone_text()
        for zone_name in ZONES:
            blocks = zones_text.get(zone_name, [])
            if not blocks:
                continue
            joined = " ".join(blocks).lower()
            seen_per_category: dict[str, set[str]] = {c: set() for c in CATEGORIES}
            for term, category in term_to_category.items():
                if term in seen_per_category[category]:
                    continue
                if " " in term:
                    if term in joined:
                        seen_per_category[category].add(term)
                else:
                    if _re.search(rf"\b{_re.escape(term)}\b", joined):
                        seen_per_category[category].add(term)
            for category, terms in seen_per_category.items():
                distinct_counts[page.url][zone_name][category] = len(terms)

    # Across-page aggregation with outlier exclusion + 0.50 multiplier.
    for zone in ZONES:
        for category in CATEGORIES:
            counts = [
                distinct_counts[p.url][zone][category] for p in pages
            ]
            if not counts:
                continue
            freqs = list(counts)
            if outlier_mode == "safe":
                outlier_indices = _detect_outliers([float(c) for c in freqs])
                if outlier_indices:
                    freqs = [
                        c for i, c in enumerate(freqs) if i not in outlier_indices
                    ]
            if not freqs:
                freqs = counts
            trimmed_max = max(freqs) if freqs else 0
            out[zone][category] = {
                "target": int(round(trimmed_max * ZONE_CATEGORY_TARGET_MULT)),
                "max": int(trimmed_max),
            }

    return out
