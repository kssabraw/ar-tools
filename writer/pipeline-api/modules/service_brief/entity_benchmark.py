"""Entity-coverage benchmark for the service page (Option B).

The service page benchmarks how many distinct entities it must cover against
the MOST AGGRESSIVE competitor — the single competitor page that covers the
most distinct entities — rather than a median. Spam outliers are excluded so
one keyword-stuffed page can't set an impossible bar, mirroring the nlp-api
Local SEO (`_aggressive_max`) and blog SIE (`SAFE_OUTLIER_MULT`) trimming.

Pure + dependency-free so it is cheap to unit-test without the research
pipeline's heavy imports (DataForSEO, SERP parsers, etc.).
"""

from __future__ import annotations

import statistics
from typing import Iterable

# A competitor page whose distinct-entity count exceeds this multiple of the
# median is treated as a spam outlier and dropped before taking the max.
# Matches the blog SIE's SAFE_OUTLIER_MULT and the nlp-api median×3 trim.
OUTLIER_MULT = 3.0


def aggressive_entity_target(per_competitor_counts: Iterable[int]) -> int:
    """The distinct-entity count of the most aggressive competitor.

    `per_competitor_counts` is one distinct-entity count per competitor page.
    Returns the highest count after dropping spam outliers (counts greater than
    OUTLIER_MULT × the median). With fewer than three competitors there is no
    stable median, so the plain max is returned.
    """
    counts = [int(c) for c in per_competitor_counts if c and c > 0]
    if not counts:
        return 0
    if len(counts) >= 3:
        median = statistics.median(counts)
        if median > 0:
            trimmed = [c for c in counts if c <= median * OUTLIER_MULT]
            if trimmed:
                counts = trimmed
    return max(counts)


def counts_from_source_urls(entity_source_urls: Iterable[Iterable[str]]) -> dict[str, int]:
    """Fold a per-entity list of source URLs into a {url: distinct-entity-count}
    map — how many distinct entities each competitor page carried."""
    per_url: dict[str, int] = {}
    for urls in entity_source_urls:
        for url in urls or []:
            if url:
                per_url[url] = per_url.get(url, 0) + 1
    return per_url
