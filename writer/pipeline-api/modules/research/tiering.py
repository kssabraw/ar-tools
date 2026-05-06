"""Source tier classification + exclusion lists.

Tier 1: government, academic, recognized health/regulatory bodies, indexed
        peer-reviewed journals
Tier 2: major news, established trade publications, recognized research firms
Tier 3: other HTTPS sources passing basic quality heuristics
Excluded: competitor SERP domains, social media, Wikipedia, HTTP-only,
          content farms
"""

from __future__ import annotations

from typing import Literal, Optional
from urllib.parse import urlparse

TierLabel = Literal[1, 2, 3]


# Tier 1 - explicit allowlist of authoritative organizations
TIER_1_DOMAINS: frozenset[str] = frozenset({
    "who.int", "cdc.gov", "fda.gov", "nih.gov", "nist.gov", "epa.gov",
    "ftc.gov", "sec.gov", "bls.gov", "census.gov", "energy.gov",
    "noaa.gov", "nasa.gov", "usda.gov", "treasury.gov", "ed.gov",
    "europa.eu", "ema.europa.eu", "ecdc.europa.eu",
    "un.org", "imf.org", "worldbank.org", "oecd.org",
    "nature.com", "science.org", "thelancet.com", "nejm.org",
    "jamanetwork.com", "bmj.com", "cell.com", "pnas.org",
    "ieee.org", "acm.org", "springer.com", "sciencedirect.com",
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
})

TIER_1_TLDS: tuple[str, ...] = (".gov", ".edu", ".mil")

# Tier 2 - major publications, trade press, research firms
TIER_2_DOMAINS: frozenset[str] = frozenset({
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "washingtonpost.com", "nytimes.com", "wsj.com",
    "ft.com", "economist.com", "bloomberg.com", "cnbc.com",
    "theatlantic.com", "newyorker.com", "guardian.co.uk", "theguardian.com",
    "npr.org", "pbs.org",
    "pewresearch.org", "gartner.com", "mckinsey.com", "statista.com",
    "forrester.com", "ibisworld.com", "deloitte.com", "pwc.com",
    "accenture.com", "bcg.com", "kpmg.com",
    "harvard.edu", "stanford.edu", "mit.edu",  # also caught by .edu but kept for explicitness
    "hbr.org", "techcrunch.com", "wired.com", "arstechnica.com",
    "theverge.com", "mit.edu",
})

# Hard-excluded categories
EXCLUDED_DOMAINS: frozenset[str] = frozenset({
    "wikipedia.org", "wikidata.org", "wiktionary.org",
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "linkedin.com", "pinterest.com", "snapchat.com",
    "reddit.com", "tumblr.com",
    "youtube.com", "vimeo.com",
    "quora.com", "medium.com",  # often UGC; can be reconsidered
})

# Content farms - poor-quality auto-generated content
CONTENT_FARMS: frozenset[str] = frozenset({
    "ehow.com", "answers.com", "wisegeek.com", "wikihow.com",
    "buzzle.com", "ezinearticles.com", "hubpages.com",
    "associatedcontent.com", "examiner.com",
})


def root_domain(url: str) -> str:
    """Extract root domain from URL, stripping leading 'www.'."""
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _matches_domain(host: str, allowlist: frozenset[str]) -> bool:
    if host in allowlist:
        return True
    return any(host.endswith("." + d) for d in allowlist)


def is_excluded(url: str, competitor_domains: frozenset[str]) -> Optional[str]:
    """Returns an exclusion reason string, or None if not excluded."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "http_only"
    host = root_domain(url)
    if not host:
        return "invalid_url"
    if host in competitor_domains or any(host.endswith("." + d) for d in competitor_domains):
        return "competitor_domain"
    if _matches_domain(host, EXCLUDED_DOMAINS):
        return "excluded_category"
    if _matches_domain(host, CONTENT_FARMS):
        return "content_farm"
    return None


def classify_tier(url: str) -> TierLabel:
    """Return tier 1/2/3. Excluded URLs should be filtered before calling."""
    host = root_domain(url)
    if any(host.endswith(tld) for tld in TIER_1_TLDS):
        return 1
    if _matches_domain(host, TIER_1_DOMAINS):
        return 1
    if _matches_domain(host, TIER_2_DOMAINS):
        return 2
    return 3


def tier_score(tier: TierLabel) -> float:
    return {1: 1.00, 2: 0.65, 3: 0.35}[tier]
