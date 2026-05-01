"""Module 12 — Word count analysis (percentile-based recommendation)."""

from __future__ import annotations

from typing import Optional

import numpy as np

from .zones import PageZones

DEFAULT_MIN_WORDS = 800
DEFAULT_MAX_WORDS = 5000


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    return int(round(float(np.percentile(values, p))))


def compute_word_count_target(
    pages: list[PageZones],
    min_filter: int = DEFAULT_MIN_WORDS,
    max_filter: int = DEFAULT_MAX_WORDS,
) -> tuple[int, int, int, list[int]]:
    """Returns (min_p25, target_p50, max_p75, source_word_counts)."""
    counts = [p.word_count for p in pages if min_filter <= p.word_count <= max_filter]
    if not counts:
        # Fall back to whatever we have
        counts = [p.word_count for p in pages if p.word_count > 0]
    if not counts:
        return (0, 0, 0, [])
    return (percentile(counts, 25), percentile(counts, 50), percentile(counts, 75), counts)
