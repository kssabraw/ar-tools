"""GBP profile audit / optimization gaps (Maps strategy PRD, Tier B / B2).

Pure analysis (no fetch): score the client's own Google Business Profile
completeness and surface gaps vs the top local-pack competitors captured by B1
(`competitor_gbp_profiles`). Drives a "fix your profile" Action Plan signal and a
workspace audit panel.

The client GBP and competitor profiles share the gbp_service shape
(gbp_category / gbp_categories / gbp_rating / gbp_review_count / description /
website / phone / photo / hours).
"""

from __future__ import annotations

import re
from collections import Counter

# Binary completeness checks run against the client's own GBP.
_MIN_DESCRIPTION_CHARS = 50
# Best-practice description length (GBP allows 750). A description that is present
# but under this reads as thin — it clears the completeness floor above yet is
# exactly what the Profile Editor loop's "improve it" trigger is for.
_GOOD_DESCRIPTION_CHARS = 200

# Generic words in a GBP category that carry no service signal on their own, so
# their presence in a description doesn't prove the core service is named.
_GENERIC_CATEGORY_WORDS = {
    "service", "services", "contractor", "contractors", "company", "business",
    "shop", "store", "and", "the", "of", "a",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: "str | None") -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _category_keywords(primary: "str | None", extras) -> set[str]:
    """Distinctive service tokens from the listing's categories (generic words
    like 'service'/'contractor' dropped, tokens under 3 chars dropped)."""
    out: set[str] = set()
    for c in [primary, *(extras or [])]:
        for w in _WORD_RE.findall((c or "").lower()):
            if len(w) >= 3 and w not in _GENERIC_CATEGORY_WORDS:
                out.add(w)
    return out


def _location_terms(g: dict) -> set[str]:
    """Best-effort location tokens for the listing: tokens from every address
    segment after the street line (city / state / zip / country) plus any
    service-area places Google lists. Empty when neither is available, so the
    missing-location signal is skipped rather than false-flagged."""
    terms: set[str] = set()
    address = g.get("address") or ""
    parts = [p.strip() for p in str(address).split(",") if p.strip()]
    # Every segment after the street line is a location candidate (city / state /
    # zip / country). Skipping the street line (parts[0]) keeps common street
    # words like "main" out of the term set; taking all the rest is robust to a
    # trailing ", USA" that would otherwise hide the city behind the state+zip.
    for seg in parts[1:]:
        terms |= {w for w in _WORD_RE.findall(seg.lower()) if len(w) >= 3}
    for place in g.get("service_area_places") or []:
        terms |= {w for w in _WORD_RE.findall(str(place).lower()) if len(w) >= 3}
    return terms


def _norm_categories(primary: "str | None", extras) -> set[str]:
    out = set()
    if primary:
        out.add(primary.strip().lower())
    for c in extras or []:
        if c and str(c).strip():
            out.add(str(c).strip().lower())
    return out


def audit(client_gbp: dict, competitor_profiles: list[dict]) -> dict:
    """Score the client's GBP completeness and compute competitor-relative gaps.
    Returns {score, checks, gaps, category_gaps, review_gap, competitor_count}.
    Pure (unit-tested)."""
    g = client_gbp or {}
    checks: list[dict] = []

    def chk(key: str, label: str, ok: bool, detail: str = "") -> None:
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail})

    desc = (g.get("description") or "").strip()
    cats = g.get("gbp_categories") or []
    chk("primary_category", "Primary category set", bool(g.get("gbp_category")))
    chk("description", "Business description", len(desc) >= _MIN_DESCRIPTION_CHARS,
        f"{len(desc)} chars" if desc else "missing")
    chk("website", "Website linked", bool(g.get("website")))
    chk("phone", "Phone number", bool(g.get("phone")))
    chk("photo", "At least one photo", bool(g.get("photo")))
    chk("hours", "Opening hours", bool(g.get("hours")))
    chk("secondary_categories", "Multiple categories", len(cats) >= 2, f"{len(cats)} categories")

    # Competitor-relative: review deficit vs the competitor median.
    review_gap = None
    comp_reviews = sorted(int(c.get("review_count") or 0) for c in competitor_profiles)
    if comp_reviews:
        median = comp_reviews[len(comp_reviews) // 2]
        client_reviews = int(g.get("gbp_review_count") or 0)
        if client_reviews < median:
            review_gap = {
                "client": client_reviews,
                "competitor_median": median,
                "deficit": median - client_reviews,
            }

    # Category gaps: categories that appear on >= half the competitors but not
    # on the client's profile (likely worth adding).
    client_cats = _norm_categories(g.get("gbp_category"), cats)
    counts: Counter = Counter()
    for c in competitor_profiles:
        for cat in _norm_categories(c.get("primary_category"), c.get("gbp_categories")):
            counts[cat] += 1
    # "Majority": present on at least half the competitors (ceil(n/2)).
    threshold = (len(competitor_profiles) + 1) // 2 if competitor_profiles else 0
    category_gaps = [
        cat for cat, n in counts.most_common() if n >= threshold and cat not in client_cats
    ][:5]

    # Description quality (separate from the binary completeness check above): a
    # present-but-weak description the Profile Editor can improve. This is the
    # signal that lets the strategist loop fire for a mature client whose
    # description already clears the completeness floor. Each issue is best-effort
    # — only asserted when its input exists, so a client with no captured
    # categories or location is never false-flagged.
    dq_issues: list[str] = []
    if desc:
        desc_words = _words(desc)
        if len(desc) < _GOOD_DESCRIPTION_CHARS:
            dq_issues.append("too_short")
        cat_keywords = _category_keywords(g.get("gbp_category"), cats)
        if cat_keywords and not (cat_keywords & desc_words):
            dq_issues.append("missing_service_keyword")
        loc_terms = _location_terms(g)
        if loc_terms and not (loc_terms & desc_words):
            dq_issues.append("missing_location")
    description_quality = {
        "ok": bool(desc) and not dq_issues,
        "length": len(desc),
        "issues": dq_issues,
    }

    passed = sum(1 for c in checks if c["ok"])
    score = round(passed / len(checks) * 100) if checks else None
    gaps = [c["label"] for c in checks if not c["ok"]]
    return {
        "score": score,
        "checks": checks,
        "gaps": gaps,
        "category_gaps": category_gaps,
        "review_gap": review_gap,
        "description_quality": description_quality,
        "competitor_count": len(competitor_profiles),
    }
