"""Stage 1 — SERP composition + intent/shape classification (PRD §4.1).

Pure, deterministic functions over the DataForSEO organic/advanced `items[]`.
The `mode` and `length_band` are derived from the LIVE SERP — never a static
per-client flag (PRD §8.2). This read gates the rest of the pipeline.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from models.service_brief import LengthBand, SerpProfile, ServiceMode

# Directories / aggregators / lead-gen marketplaces — their presence signals a
# competitive local/commercial SERP, but they are NOT modelled as competitor
# service pages to tear down (PRD §4.2 filters them out).
DIRECTORY_DOMAINS: frozenset[str] = frozenset({
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "homeadvisor.com",
    "bbb.org", "yellowpages.com", "manta.com", "houzz.com", "porch.com",
    "expertise.com", "trustpilot.com", "g2.com", "capterra.com", "clutch.co",
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com",
    "reddit.com", "quora.com", "wikipedia.org", "amazon.com", "indeed.com",
    "mapquest.com", "nextdoor.com", "bark.com",
})

# Listicle / editorial titles ("10 Best…", "Top Plumbers…", "X vs Y"). These
# rank but aren't service pages — excluded from the teardown set.
_LISTICLE_RE = re.compile(
    r"\b(\d+\s+best|best\s+\d+|top\s+\d+|\d+\s+top|"
    r"vs\.?|versus|compare|comparison|reviews?\s+of|ultimate guide)\b",
    re.IGNORECASE,
)

# Length bands → target word counts (tunable starting values). Retained only as
# a coarse label + a fallback for the SERP-anchored target below (when too few
# competitor pages scrape to yield a reliable average).
_BAND_WORDS: dict[LengthBand, int] = {"short": 700, "medium": 1200, "long": 1800}

# ── SERP-anchored length target (mirrors nlp-api length_fit.py) ────────────────
# Service pages used to be sized by a fixed band (700/1200/1800) with no
# relationship to the pages they actually compete with, so they ran 2–3× longer
# than the competitor SERP — the same bloat the Local SEO writer had before #781.
# The fix is identical: target the competitor SERP average + 20%, floored, so the
# SERP drives LENGTH while the client's reference structure drives LAYOUT. Purely
# deterministic — the LLM never counts words. The floor value + multiplier match
# nlp-api's `length_fit` so the writer's budget and the scorer's length_fit engine
# aim at the same band.
LENGTH_OVERAGE_MULTIPLIER = 1.20
# Absolute floor (owner-chosen; matches nlp-api LENGTH_MIN_TARGET_WORDS). Only ever
# RAISES a real, avg-derived target — never manufactures one from a SERP that
# yielded no usable competitor length.
MIN_LENGTH_TARGET_WORDS = int(os.environ.get("SERVICE_LENGTH_MIN_TARGET_WORDS", "900"))
# A competitor page that scraped to near-nothing is a failed/thin scrape, not a
# real length signal — exclude it so it can't drag the average (and target) down.
_MIN_VALID_COMPETITOR_WORDS = 100


def competitor_avg_words(word_counts: list[int]) -> float | None:
    """Average competitor body word count across the SERP, dropping thin/failed
    scrapes. Returns ``None`` when fewer than 2 valid pages remain (no reliable
    target — the caller then falls back to the band). Mirrors
    ``length_fit.competitor_avg_words`` so the service writer and the nlp-api
    length_fit scorer measure the same thing."""
    valid = [
        c for c in (word_counts or [])
        if isinstance(c, int) and c >= _MIN_VALID_COMPETITOR_WORDS
    ]
    if len(valid) < 2:
        return None
    return sum(valid) / len(valid)


def serp_word_target(avg_words: float | None) -> int | None:
    """Competitor SERP average + 20%, floored at ``MIN_LENGTH_TARGET_WORDS``.
    ``None`` when there is no usable average (the caller keeps the band target, so
    a thin SERP never produces a nonsense length). Mirrors ``length_fit.word_target``."""
    if not avg_words or avg_words <= 0:
        return None
    return max(int(round(avg_words * LENGTH_OVERAGE_MULTIPLIER)), MIN_LENGTH_TARGET_WORDS)


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_directory_or_aggregator(url: str) -> bool:
    dom = _domain(url)
    return any(dom == d or dom.endswith("." + d) for d in DIRECTORY_DOMAINS)


def is_listicle(title: str) -> bool:
    return bool(_LISTICLE_RE.search(title or ""))


def filter_service_page_urls(items: list[dict]) -> list[str]:
    """Top organic URLs that look like real service pages.

    Drops directories/aggregators and listicle/editorial results, preserving
    SERP rank order. These are the pages the teardown stage will scrape.
    """
    urls: list[str] = []
    for item in items:
        if item.get("type") != "organic":
            continue
        url = (item.get("url") or "").strip()
        title = item.get("title") or ""
        if not url:
            continue
        if is_directory_or_aggregator(url):
            continue
        if is_listicle(title):
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _count_organic_buckets(items: list[dict]) -> tuple[int, int, int]:
    """Return (service_pages, directories, informational/listicles) counts."""
    service = directories = informational = 0
    for item in items:
        if item.get("type") != "organic":
            continue
        url = item.get("url") or ""
        title = item.get("title") or ""
        if is_directory_or_aggregator(url):
            directories += 1
        elif is_listicle(title):
            informational += 1
        else:
            service += 1
    return service, directories, informational


def _band_for_mode(mode: ServiceMode) -> LengthBand:
    # Local service pages tend to be tighter conversion pages; national/B2B
    # pages tend to be longer and more depth-driven. Refined later from the
    # competitor median word count when available.
    return "medium" if mode == "local_service" else "long"


def target_words_for_band(band: LengthBand) -> int:
    return _BAND_WORDS.get(band, 1200)


def band_for_word_count(words: int) -> LengthBand:
    if words <= 0:
        return "medium"
    if words < 900:
        return "short"
    if words < 1500:
        return "medium"
    return "long"


def classify_serp(
    items: list[dict],
    *,
    location: str | None = None,
    has_local_pack: bool = False,
    has_featured_snippet: bool = False,
    search_intent: str | None = None,
) -> SerpProfile:
    """Classify the SERP into a service-page `mode` + `length_band`.

    `mode` is `local_service` when the SERP shows a local pack (or a location
    was supplied AND directories dominate the organic set), else `national_b2b`.
    Derived from the live SERP, not a per-client flag.
    """
    service, directories, informational = _count_organic_buckets(items)

    local_signal = has_local_pack or (
        bool(location) and directories >= max(2, service)
    )
    mode: ServiceMode = "local_service" if local_signal else "national_b2b"
    band = _band_for_mode(mode)

    return SerpProfile(
        mode=mode,
        length_band=band,
        target_word_count=target_words_for_band(band),
        local_pack=has_local_pack,
        featured_snippet=has_featured_snippet,
        organic_service_pages=service,
        directory_aggregator_count=directories,
        informational_count=informational,
        search_intent=search_intent,
    )
