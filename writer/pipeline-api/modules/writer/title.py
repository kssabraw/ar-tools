"""Step 1 + 2 — Title generation and H1 enrichment.

Title rules per intent (PRD §6 Step 1):
- how-to: starts with "How to" or "How [Audience] Can"
- listicle: leads with a number
- comparison: includes "vs." or "or"
- others: declarative, value-led

SIE v1.4 — both functions consume the three-bucket per-zone aggregate
target (entities / related_keywords / keyword_variants) computed by
SIE at 0.50 × trimmed-max competitor count. Lists carry the actual
candidate terms; targets carry "include at least N of each" counts.
"""

from __future__ import annotations

import logging
from typing import Optional

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


TITLE_SYSTEM = (
    "You write SEO-optimized blog post titles. Output is a single JSON object: "
    '{"candidates": ["title 1", "title 2", "title 3"]}.'
)


def _intent_guidance(intent: str) -> str:
    return {
        "how-to": "Start with 'How to' or 'How [Audience] Can'.",
        "listicle": "Lead with a number (e.g., '7 Reasons...').",
        "comparison": "Include 'vs.' or 'or'.",
        "informational": "Declarative, value-led statement.",
        "informational-commercial": "Buyer-education declarative title.",
        "local-seo": "Declarative; service framing acceptable.",
        "ecom": "Feature-benefit framing; not promotional.",
        "news": "Recency-forward, factual.",
    }.get(intent, "Declarative statement.")


def _format_category_directive(
    name: str,
    target: int,
    items_listed: int,
) -> Optional[str]:
    """Build a "include at least N {name}" directive line, clamped by the
    number of items we actually list. Returns None when there's nothing
    to say (zero target or no listed items)."""
    if target <= 0 or items_listed <= 0:
        return None
    effective = min(target, items_listed)
    plural = name if effective != 1 else name.rstrip("s") or name
    return f"  - include at least {effective} {plural}"


async def generate_title(
    keyword: str,
    intent_type: str,
    *,
    entities: list[str],
    related_keywords: list[str],
    keyword_variants: list[str],
    title_targets: dict[str, int],
) -> str:
    """Generate 3 candidates and pick the one with best coverage.

    `title_targets` is the SIE v1.4 zone aggregate keyed by category:
    `{"entities": int, "related_keywords": int, "keyword_variants": int}`.
    Values are 0.50 × trimmed-max competitor distinct-item count for
    the title zone. Each list carries the candidate terms (already
    truncated to a sensible top-N by the caller) the LLM should pick
    from.
    """
    # Title is a short zone — cap each list aggressively. The SIE
    # aggregate may legitimately be 4+ for entities, but a 70-char
    # title can only carry ~3 distinct categories without keyword
    # stuffing. Show enough candidates that the LLM has choice but
    # don't overload the prompt.
    top_entities = entities[:5]
    top_related = related_keywords[:5]
    top_variants = keyword_variants[:3]

    directives = [
        d for d in (
            _format_category_directive("entities", title_targets.get("entities", 0), len(top_entities)),
            _format_category_directive("related keywords", title_targets.get("related_keywords", 0), len(top_related)),
            _format_category_directive("keyword variants", title_targets.get("keyword_variants", 0), len(top_variants)),
        )
        if d
    ]
    if directives:
        coverage_block = "Coverage targets (incorporate naturally):\n" + "\n".join(directives)
    else:
        coverage_block = "Aim for keyword + entity coverage over brevity."

    user = (
        f"Keyword: {keyword}\n"
        f"Intent: {intent_type}\n"
        f"Style: {_intent_guidance(intent_type)}\n\n"
        f"Entities: {', '.join(top_entities) if top_entities else 'none'}\n"
        f"Related keywords: {', '.join(top_related) if top_related else 'none'}\n"
        f"Keyword variants: {', '.join(top_variants) if top_variants else 'none'}\n\n"
        f"{coverage_block}\n\n"
        "Write 3 distinct title candidates. Each must contain the seed "
        "keyword. Avoid promotional superlatives."
    )

    try:
        result = await claude_json(TITLE_SYSTEM, user, max_tokens=300, temperature=0.6)
        candidates = (result.get("candidates") if isinstance(result, dict) else None) or []
        candidates = [c.strip() for c in candidates if isinstance(c, str) and c.strip()]
    except Exception as exc:
        logger.warning("Title generation failed: %s", exc)
        candidates = []

    if not candidates:
        return f"{keyword.title()} — A Complete Guide"

    all_terms = top_entities + top_related + top_variants

    def coverage(c: str) -> int:
        lowered = c.lower()
        score = 0
        if keyword.lower() in lowered:
            score += 5
        for term in all_terms:
            if term and term.lower() in lowered:
                score += 1
        return score

    best = max(candidates, key=coverage)
    if keyword.lower() not in best.lower():
        best = f"{keyword.title()}: {best}"
    return best


async def generate_h1_enrichment(
    keyword: str,
    h1_text: str,
    *,
    entities: list[dict],
    related_keywords: list[str],
    keyword_variants: list[str],
    h1_targets: dict[str, int],
) -> str:
    """A 1-sentence lede (≤25 words) immediately after the H1.

    `entities` carries entity dicts (with `term` and `entity_category`)
    so we can filter to lede-relevant categories (services / equipment
    / problems / methods); `related_keywords` and `keyword_variants`
    are simple term-string lists. `h1_targets` is the SIE v1.4 h1-zone
    aggregate, same shape as `title_targets` in generate_title.
    """
    # The lede only carries entity categories that fit a lede sentence
    # naturally — services / equipment / problems / methods. Other
    # entity types (locations, brands, people) read as filler. Keyword
    # variants and related keywords have no such category restriction.
    relevant_entities = [
        e for e in entities
        if e.get("entity_category") in ("services", "equipment", "problems", "methods")
    ][:3]
    top_related = related_keywords[:3]
    top_variants = keyword_variants[:2]

    if not relevant_entities and not top_related and not top_variants:
        return ""

    # 25-word lede can't carry more than ~3 distinct items total
    # without losing readability. Cap each category contribution at 2
    # so the directive is achievable.
    LEDE_PER_CATEGORY_CEILING = 2

    def _clamp(name: str, target: int, listed: int) -> Optional[str]:
        if target <= 0 or listed <= 0:
            return None
        eff = min(target, listed, LEDE_PER_CATEGORY_CEILING)
        plural = name if eff != 1 else name.rstrip("s") or name
        return f"  - include at least {eff} {plural}"

    directives = [
        d for d in (
            _clamp("entities", h1_targets.get("entities", 0), len(relevant_entities)),
            _clamp("related keywords", h1_targets.get("related_keywords", 0), len(top_related)),
            _clamp("keyword variants", h1_targets.get("keyword_variants", 0), len(top_variants)),
        )
        if d
    ]
    coverage_block = (
        "Coverage targets:\n" + "\n".join(directives)
        if directives
        else "Weave in 1-2 of the listed terms naturally."
    )

    entity_list = ", ".join(e.get("term", "") for e in relevant_entities) or "none"
    related_list = ", ".join(top_related) if top_related else "none"
    variants_list = ", ".join(top_variants) if top_variants else "none"

    system = (
        "You write a single sentence (max 25 words) that introduces a blog "
        "section. The sentence is NOT a heading. No promotional language. "
        "Output JSON: {\"sentence\": \"...\"}."
    )
    user = (
        f"Topic: {h1_text}\n"
        f"Keyword to include or echo: {keyword}\n\n"
        f"Entities: {entity_list}\n"
        f"Related keywords: {related_list}\n"
        f"Keyword variants: {variants_list}\n\n"
        f"{coverage_block}\n\n"
        "Write the lede sentence. Concise, factual, no marketing tone."
    )
    try:
        result = await claude_json(system, user, max_tokens=120, temperature=0.4)
        sentence = result.get("sentence", "") if isinstance(result, dict) else ""
        if isinstance(sentence, str):
            return sentence.strip()
    except Exception as exc:
        logger.warning("H1 enrichment failed: %s", exc)
    return ""
