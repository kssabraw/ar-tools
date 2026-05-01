"""Module 3 — SERP URL classification.

Heuristic-based classifier that decides whether a URL is content-eligible
for n-gram and entity analysis. We deliberately avoid an LLM call here —
the rules are deterministic and the cost is negligible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

DIRECTORY_DOMAINS = {
    "yelp.com", "yellowpages.com", "bbb.org", "angi.com", "angieslist.com",
    "houzz.com", "manta.com", "thumbtack.com", "homeadvisor.com",
}
FORUM_DOMAINS = {
    "reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com",
}
SOCIAL_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
    "tiktok.com", "pinterest.com",
}
VIDEO_DOMAINS = {
    "youtube.com", "youtu.be", "vimeo.com",
}
MARKETPLACE_DOMAINS = {
    "amazon.com", "ebay.com", "etsy.com", "walmart.com", "target.com",
    "homedepot.com", "lowes.com", "wayfair.com",
}
NEWS_DOMAINS = {
    "nytimes.com", "wsj.com", "washingtonpost.com", "bbc.com", "cnn.com",
    "reuters.com", "apnews.com",
}
GOV_EDU_TLDS = (".gov", ".edu", ".mil")


@dataclass
class ClassifiedURL:
    url: str
    rank: int
    title: str
    page_category: str
    content_eligible: bool
    reason: str
    domain: str = ""


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        # Strip leading www.
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_subdomain_of(host: str, parent: str) -> bool:
    return host == parent or host.endswith("." + parent)


def classify(url: str, rank: int, title: str = "") -> ClassifiedURL:
    """Classify a single SERP URL. Returns ClassifiedURL with eligibility flag."""
    host = _domain(url)
    if not host:
        return ClassifiedURL(
            url=url, rank=rank, title=title,
            page_category="irrelevant",
            content_eligible=False,
            reason="invalid_url",
            domain="",
        )

    if any(host.endswith(tld) for tld in GOV_EDU_TLDS):
        return ClassifiedURL(
            url=url, rank=rank, title=title,
            page_category="government_educational",
            content_eligible=True,
            reason="gov/edu domain — high authority",
            domain=host,
        )

    for d in NEWS_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="news",
                content_eligible=True,
                reason="news outlet",
                domain=host,
            )

    for d in DIRECTORY_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="directory",
                content_eligible=False,
                reason="Directory result",
                domain=host,
            )

    for d in FORUM_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="forum_ugc",
                content_eligible=False,
                reason="Forum / UGC result",
                domain=host,
            )

    for d in SOCIAL_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="social_media",
                content_eligible=False,
                reason="Social media result",
                domain=host,
            )

    for d in VIDEO_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="video",
                content_eligible=False,
                reason="Video result",
                domain=host,
            )

    for d in MARKETPLACE_DOMAINS:
        if _is_subdomain_of(host, d):
            return ClassifiedURL(
                url=url, rank=rank, title=title,
                page_category="marketplace",
                content_eligible=False,
                reason="Marketplace page",
                domain=host,
            )

    # Default: assume informational article unless URL path screams "service area"
    path = urlparse(url).path.lower()
    if any(p in path for p in ("/services", "/locations", "/service-area", "/areas-served")):
        return ClassifiedURL(
            url=url, rank=rank, title=title,
            page_category="local_service_page",
            content_eligible=True,
            reason="local service page",
            domain=host,
        )

    return ClassifiedURL(
        url=url, rank=rank, title=title,
        page_category="informational_article",
        content_eligible=True,
        reason="informational article (default)",
        domain=host,
    )


def classify_all(urls: list[tuple[str, int, str]]) -> list[ClassifiedURL]:
    """Classify a batch. Input: [(url, rank, title), ...]."""
    return [classify(u, r, t) for (u, r, t) in urls]


def dominant_page_type(classified: list[ClassifiedURL]) -> str:
    if not classified:
        return ""
    counts: dict[str, int] = {}
    for c in classified:
        counts[c.page_category] = counts.get(c.page_category, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def near_duplicate_pairs(
    pages: list[tuple[str, int, str]],
    threshold: float = 0.90,
) -> list[tuple[str, str, float]]:
    """Detect near-duplicate pages by comparing the first 500 chars of cleaned text.

    pages: [(url, rank, cleaned_text), ...]
    Returns list of (lower_ranked_url, higher_ranked_url, similarity).
    """
    out: list[tuple[str, str, float]] = []
    snapshots: list[tuple[str, int, str]] = []
    for url, rank, text in pages:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()[:500]
        if normalized:
            snapshots.append((url, rank, normalized))

    snapshots.sort(key=lambda x: x[1])  # rank ascending

    for i in range(len(snapshots)):
        for j in range(i + 1, len(snapshots)):
            sim = _char_similarity(snapshots[i][2], snapshots[j][2])
            if sim >= threshold:
                # Higher rank number = lower-ranked = duplicate of i (the canonical).
                out.append((snapshots[j][0], snapshots[i][0], sim))
    return out


def _char_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Cheap character-level Jaccard on bigrams; faster than Levenshtein and
    # adequate for the >90% threshold used by the duplicate detector.
    a_bigrams = {a[i:i + 2] for i in range(len(a) - 1)}
    b_bigrams = {b[i:i + 2] for i in range(len(b) - 1)}
    if not a_bigrams or not b_bigrams:
        return 0.0
    intersection = len(a_bigrams & b_bigrams)
    union = len(a_bigrams | b_bigrams)
    return intersection / union if union else 0.0
