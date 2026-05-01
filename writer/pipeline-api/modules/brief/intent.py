"""Step 3 — Intent classification.

Rules-based first; LLM check on borderline ecom cases.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.brief import IntentSignals, IntentType

from .llm import claude_json

logger = logging.getLogger(__name__)


# Conflict priority (highest wins): news > ecom > local-seo > comparison > how-to > listicle > informational
INTENT_PRIORITY: list[IntentType] = [
    "news",
    "ecom",
    "local-seo",
    "comparison",
    "how-to",
    "listicle",
    "informational",
]


def _has_pattern(titles: list[str], pattern: str, min_count: int = 3) -> bool:
    count = sum(1 for t in titles[:5] if pattern in t.lower())
    return count >= min_count


def _is_numbered_listicle(titles: list[str]) -> bool:
    import re
    pattern = re.compile(r"^\s*(\d+)\s+")
    count = sum(1 for t in titles[:5] if pattern.match(t))
    return count >= 3


def classify_rules(signals: IntentSignals, titles: list[str]) -> tuple[IntentType, float]:
    """Apply rule mapping. Returns (intent, confidence)."""
    matches: list[tuple[IntentType, float]] = []

    if signals.shopping_box:
        matches.append(("ecom", 0.85))
    if signals.news_box:
        matches.append(("news", 0.9))
    if signals.local_pack:
        matches.append(("local-seo", 0.9))
    if _has_pattern(titles, " vs ") or _has_pattern(titles, " versus ") or signals.comparison_tables:
        matches.append(("comparison", 0.85))
    if _has_pattern(titles, "how to"):
        matches.append(("how-to", 0.9))
    if _is_numbered_listicle(titles):
        matches.append(("listicle", 0.85))
    if signals.featured_snippet and not (signals.shopping_box or signals.news_box or signals.local_pack):
        matches.append(("informational", 0.8))

    if not matches:
        return ("informational", 0.55)

    by_priority = sorted(matches, key=lambda m: INTENT_PRIORITY.index(m[0]))
    return by_priority[0]


async def borderline_ecom_check(
    keyword: str,
    titles: list[str],
    signals: IntentSignals,
    top_3_domains: list[str],
) -> Optional[IntentType]:
    """Trigger an LLM check when initial intent is ecom AND any of:
    - Top 5 titles contain "best", "top", "review", "guide"
    - Featured snippet is present
    - Top 3 results are not e-commerce domains
    Returns one of: ecom, comparison, informational-commercial.
    """
    has_best = any(
        kw in t.lower()
        for t in titles[:5]
        for kw in ("best", "top", "review", "guide")
    )
    ecom_tlds = {".shop", ".store"}
    ecom_keywords = {"amazon", "walmart", "target", "etsy", "ebay", "shopify", "wayfair", "homedepot"}
    not_ecom = sum(
        1
        for d in top_3_domains
        if not any(kw in d.lower() for kw in ecom_keywords)
        and not any(d.lower().endswith(t) for t in ecom_tlds)
    ) >= 2

    if not (has_best or signals.featured_snippet or not_ecom):
        return None

    system = (
        "You classify search intent. Respond with a single JSON object: "
        '{"intent": "ecom" | "comparison" | "informational-commercial"}.'
    )
    user = (
        f"Keyword: {keyword}\n"
        f"Top SERP titles:\n- " + "\n- ".join(titles[:5]) + "\n"
        f"Top 3 domains: {top_3_domains}\n"
        f"Featured snippet present: {signals.featured_snippet}\n"
        "Classify the intent."
    )
    try:
        result = await claude_json(system, user, max_tokens=80, temperature=0)
        intent = result.get("intent")
        if intent in ("ecom", "comparison", "informational-commercial"):
            return intent
    except Exception as exc:
        logger.warning("borderline_ecom_check failed: %s", exc)
    return None


async def classify_intent(
    keyword: str,
    signals: IntentSignals,
    titles: list[str],
    top_3_domains: list[str],
    override: Optional[IntentType] = None,
) -> tuple[IntentType, float, bool]:
    """Returns (intent_type, confidence, review_required)."""
    if override:
        return (override, 1.0, False)

    intent, confidence = classify_rules(signals, titles)

    if intent == "ecom":
        revised = await borderline_ecom_check(keyword, titles, signals, top_3_domains)
        if revised:
            intent = revised
            confidence = max(confidence, 0.8)

    if confidence < 0.5:
        intent = "informational"
        confidence = 0.5
        return (intent, confidence, True)

    return (intent, confidence, confidence < 0.75)
