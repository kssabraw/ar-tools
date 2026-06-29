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

from collections import Counter

# Binary completeness checks run against the client's own GBP.
_MIN_DESCRIPTION_CHARS = 50


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

    passed = sum(1 for c in checks if c["ok"])
    score = round(passed / len(checks) * 100) if checks else None
    gaps = [c["label"] for c in checks if not c["ok"]]
    return {
        "score": score,
        "checks": checks,
        "gaps": gaps,
        "category_gaps": category_gaps,
        "review_gap": review_gap,
        "competitor_count": len(competitor_profiles),
    }
