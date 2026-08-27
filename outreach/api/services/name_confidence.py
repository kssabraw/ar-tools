"""Confidence scores for the additional-research name sources. PURE.

Site-scrape and web-search fallback names are lower-trust than an Outscraper pull, so each carries a
0-100 confidence + a High/Medium/Low band on ONE shared scale:

  * **site scrape — DETERMINISTIC**, from provenance signals available at extraction: structured
    JSON-LD beats role-anchored text, an explicit senior-ownership role adds trust, and a name found
    on MULTIPLE pages of the site corroborates itself.
  * **web search — BLENDED**: a deterministic corroboration backbone (how many DISTINCT sources cite
    the name, whether a source ties the person to THIS business's own domain) PLUS the model's own
    self-rating as one weighted input — never the model's opinion alone (the module's fact-grounded
    posture: an LLM's self-confidence is easily overconfident, so it MOVES the score, it doesn't SET
    it).

Bands, thresholds and weights are module constants so they can be calibrated from real runs. This
module is pure — it takes already-extracted signals and returns a number; it never fetches or calls
a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# Band thresholds (inclusive lower bounds). Calibrate from real runs.
HIGH_MIN = 75
MEDIUM_MIN = 50

# Deterministic-vs-model blend for web search — the deterministic backbone dominates.
DETERMINISTIC_WEIGHT = 0.65
MODEL_WEIGHT = 0.35

# Senior ownership/management titles — higher trust when the role is explicit. Lower-cased.
_STRONG_TITLES = frozenset(
    {
        "owner", "owner/operator", "co-owner", "founder", "co-founder", "proprietor",
        "president", "president & ceo", "ceo", "coo", "cfo", "managing director",
        "managing partner", "principal",
    }
)


@dataclass(frozen=True)
class Confidence:
    score: int          # 0-100
    band: str           # high | medium | low
    factors: dict[str, Any]


def band_for(score: int) -> str:
    if score >= HIGH_MIN:
        return "high"
    if score >= MEDIUM_MIN:
        return "medium"
    return "low"


def _clamp(n: float) -> int:
    return max(0, min(100, int(round(n))))


def _is_strong_title(title: str | None) -> bool:
    return bool(title) and title.strip().lower() in _STRONG_TITLES


def score_site_scrape(*, source_kind: str | None, title: str | None, page_count: int = 1) -> Confidence:
    """Deterministic confidence for a site-scraped name. Structured data (JSON-LD) is the strongest
    signal; an explicit senior role and appearing on ≥2 pages of the site each add corroboration."""
    base = 65 if source_kind == "jsonld" else 45
    role = 12 if _is_strong_title(title) else 0
    multi_page = 18 if (page_count or 1) >= 2 else 0
    titled = 5 if title else 0
    score = _clamp(base + role + multi_page + titled)
    return Confidence(
        score, band_for(score),
        {"kind": "site_scrape", "base": base, "strong_role": role, "multi_page": multi_page,
         "titled": titled, "source_kind": source_kind, "page_count": page_count or 1},
    )


def _registrable(host: str | None) -> str:
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return _registrable(urlsplit(url).hostname or urlsplit(f"//{url}").hostname or "")
    except ValueError:
        return ""


def distinct_citation_domains(citations: Any) -> int:
    return len({_domain(c) for c in (citations or []) if _domain(c)})


def business_domain_cited(business_website: str | None, citations: Any) -> bool:
    """Whether any citation is on the business's OWN registrable domain — corroboration that the
    search resolved the RIGHT entity (not a namesake)."""
    biz = _domain(business_website)
    if not biz:
        return False
    return any(_domain(c) == biz for c in (citations or []))


def score_web_search(
    *, model_confidence: int | None = None, citations: Any = (), business_website: str | None = None
) -> Confidence:
    """Blended confidence for a web-searched name. A deterministic corroboration backbone (distinct
    citing sources + a source on the business's own domain) is the primary signal; the model's own
    self-rating, when present, is blended in at `MODEL_WEIGHT`."""
    n_domains = distinct_citation_domains(citations)
    base = 40
    corrob = 0 if n_domains <= 1 else (12 if n_domains == 2 else 20)
    own = 10 if business_domain_cited(business_website, citations) else 0
    deterministic = _clamp(base + corrob + own)

    factors: dict[str, Any] = {
        "kind": "web_search", "citations": len(list(citations or [])),
        "distinct_domains": n_domains, "corroboration": corrob,
        "business_domain_cited": bool(own), "deterministic": deterministic,
    }
    if model_confidence is None:
        score = deterministic
    else:
        m = _clamp(model_confidence)
        factors["model_confidence"] = m
        score = _clamp(DETERMINISTIC_WEIGHT * deterministic + MODEL_WEIGHT * m)
    return Confidence(score, band_for(score), factors)
