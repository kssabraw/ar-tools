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

# ── Writing-quality trip-wires (SED Society GBP Description SOP) ──────────────
# A well-written description names what/where/who and reads naturally; a weak one
# keyword-stuffs, leans on generic marketing filler, or opens with fluff. These
# detectors are deliberately HIGH-PRECISION so a strong description is never
# false-flagged — the fuzzier judgement (differentiators, use cases, natural
# voice) is left to the LLM rewrite that the SOP grounds.

# A single captured location term repeated at least this many times reads as
# city-stuffing (the SOP's sharpest rule: establish geography once, don't repeat
# the city). Natural reinforcement (open + a closing service-area line) is 2–3.
_STUFFING_REPEAT = 4

# Promotional superlatives the SOP says to drop (kept in step with the editor
# linter's advisory list — one vocabulary, two surfaces).
_SUPERLATIVE_RE = re.compile(
    r"\b(best|#\s*1|number\s+one|top[- ]?rated|highest[- ]?rated|guarantee[ds]?|"
    r"unbeatable|world[- ]?class|award[- ]?winning|cheapest|lowest\s+price[sd]?)\b",
    re.IGNORECASE,
)

# Generic marketing filler the SOP says to replace with specifics — matched as
# whole phrases so an ordinary sentence never trips one.
_FILLER_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"customer satisfaction is our",
    r"satisfaction is our (?:number one |#\s*1 |top |No\.?\s*1 )?priority",
    r"we pride ourselves",
    r"your satisfaction is our (?:success|priority|goal)",
    r"we go above and beyond",
    r"treat(?:s|ed|ing)? (?:you|every ?one|every customer|our customers|each customer|all our customers) like family",
    r"customer satisfaction is (?:our )?(?:top|number one|#\s*1) priority",
    r"quality (?:work )?and customer satisfaction",
    r"second to none",
    r"where quality (?:and|meets)",
))

# Descriptions that open with marketing fluff instead of establishing the
# business (the SOP: the first sentence is valuable — use it for what/where/who).
_GENERIC_OPENING_RE = re.compile(
    r"^\W*(welcome to|looking for|are you looking|in need of|need (?:a|an|your)|"
    r"searching for|thank you for)\b",
    re.IGNORECASE,
)


def _words(text: "str | None") -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def find_superlatives(text: "str | None") -> list[str]:
    """The promotional superlatives present in the text (SOP §15). Pure."""
    return [m.group(0) for m in _SUPERLATIVE_RE.finditer(text or "")]


def find_marketing_filler(text: "str | None") -> list[str]:
    """The generic-marketing-filler phrases present in the text (SOP §10). Pure."""
    out: list[str] = []
    for rx in _FILLER_RES:
        m = rx.search(text or "")
        if m:
            out.append(m.group(0).strip())
    return out


def has_generic_opening(text: "str | None") -> bool:
    """True when the description LEADS with marketing fluff (SOP §15). Pure."""
    return bool(_GENERIC_OPENING_RE.match((text or "").strip()))


def overused_terms(text: "str | None", terms: "set[str]", threshold: int = _STUFFING_REPEAT) -> list[str]:
    """Which of ``terms`` (e.g. the listing's location tokens) appear at least
    ``threshold`` times in the text — the SOP's city-stuffing signal. Pure."""
    if not terms:
        return []
    counts = Counter(_WORD_RE.findall((text or "").lower()))
    return sorted(t for t in terms if counts.get(t, 0) >= threshold)


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
    # Beyond thin/missing-keyword/missing-location, the SED Society SOP wants
    # keyword-stuffing, promotional superlatives, generic marketing filler, and
    # fluff openings flagged as rewrite triggers. Each is high-precision, so a
    # naturally-written description clears them all.
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
        # City-stuffing — a captured location term repeated (best-effort: only
        # when location terms are known, so it's never false-flagged).
        if loc_terms and overused_terms(desc, loc_terms):
            dq_issues.append("keyword_stuffed")
        if find_superlatives(desc):
            dq_issues.append("promotional_superlatives")
        if find_marketing_filler(desc):
            dq_issues.append("marketing_filler")
        if has_generic_opening(desc):
            dq_issues.append("generic_opening")
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
