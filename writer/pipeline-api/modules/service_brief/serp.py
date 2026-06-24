"""Stage 1 — SERP composition + intent/shape classification (PRD §4.1).

Pure, deterministic functions over the DataForSEO organic/advanced `items[]`.
The `mode` and `length_band` are derived from the LIVE SERP — never a static
per-client flag (PRD §8.2). This read gates the rest of the pipeline.
"""

from __future__ import annotations

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

# Length bands → target word counts (tunable starting values).
_BAND_WORDS: dict[LengthBand, int] = {"short": 700, "medium": 1200, "long": 1800}


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
