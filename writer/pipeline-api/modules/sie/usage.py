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
