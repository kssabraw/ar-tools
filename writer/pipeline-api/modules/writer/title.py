"""Step 1 + 2 — Title generation and H1 enrichment.

Title rules per intent (PRD §6 Step 1):
- how-to: starts with "How to" or "How [Audience] Can"
- listicle: leads with a number
- comparison: includes "vs." or "or"
- others: declarative, value-led
"""

from __future__ import annotations

import logging
from typing import Optional

from modules.brief.llm import claude_json, claude_text

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


async def generate_title(
    keyword: str,
    intent_type: str,
    required_terms: list[str],
    entities: list[str],
    title_zone_target: int = 0,
    title_zone_max: int = 0,
) -> str:
    """Generate 3 candidates and pick the one with best keyword + entity coverage.

    `title_zone_target` / `title_zone_max` come from the SIE
    `usage_recommendations[*].usage.title` aggregate across recommended
    entities (PRD v2.6 wiring) — they tell the LLM how many distinct
    entities to fit naturally and the absolute ceiling beyond which
    titles read like keyword-stuffed grocery lists.
    """
    top_terms = required_terms[:8]
    top_entities = entities[:5]
    # Clamp the directive count by the entities we actually list so the
    # prompt can't ask for "at least 30" when only 5 are shown — that
    # framing is impossible and confuses the LLM.
    effective_target = min(title_zone_target, len(top_entities)) if title_zone_target > 0 else 0
    effective_max = min(title_zone_max, len(top_entities)) if title_zone_max > 0 else 0
    if effective_max and effective_max < effective_target:
        effective_max = effective_target
    if effective_target > 0:
        coverage_directive = (
            f"Aim to incorporate at least {effective_target} of the listed "
            f"entities naturally"
        )
        if effective_max > 0:
            coverage_directive += f" (do not exceed {effective_max} entities)"
        coverage_directive += "."
    else:
        coverage_directive = (
            "Aim for keyword + entity coverage over brevity."
        )
    user = (
        f"Keyword: {keyword}\n"
        f"Intent: {intent_type}\n"
        f"Style: {_intent_guidance(intent_type)}\n"
        f"Required terms (incorporate where natural): {', '.join(top_terms) if top_terms else 'none'}\n"
        f"Entities (incorporate where natural): {', '.join(top_entities) if top_entities else 'none'}\n\n"
        f"Write 3 distinct title candidates. Each must contain the seed keyword. "
        f"{coverage_directive} Avoid promotional superlatives."
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

    def coverage(c: str) -> int:
        lowered = c.lower()
        score = 0
        if keyword.lower() in lowered:
            score += 5
        for term in top_terms:
            if term.lower() in lowered:
                score += 2
        for ent in top_entities:
            if ent.lower() in lowered:
                score += 1
        return score

    best = max(candidates, key=coverage)
    if keyword.lower() not in best.lower():
        best = f"{keyword.title()}: {best}"
    return best


async def generate_h1_enrichment(
    keyword: str,
    h1_text: str,
    high_salience_entities: list[dict],
    h1_zone_target: int = 0,
    h1_zone_max: int = 0,
) -> str:
    """A 1-sentence lede (≤25 words) immediately after the H1.

    Must include 1-2 entities from categories: services, equipment, problems, methods.

    `h1_zone_target` / `h1_zone_max` come from the SIE
    `usage_recommendations[*].usage.h1` aggregate across recommended
    entities (PRD v2.6 wiring). When provided, the prompt asks for at
    least `h1_zone_target` entities (capped at `h1_zone_max`); when
    absent, the legacy "1-2 most natural" copy is used.
    """
    relevant_entities = [
        e for e in high_salience_entities
        if e.get("entity_category") in ("services", "equipment", "problems", "methods")
    ][:3]
    if not relevant_entities:
        # Skip enrichment when no qualifying entities exist
        return ""

    entity_list = ", ".join(e.get("term", "") for e in relevant_entities)
    system = (
        "You write a single sentence (max 25 words) that introduces a blog "
        "section. The sentence is NOT a heading. No promotional language. "
        "Output JSON: {\"sentence\": \"...\"}."
    )
    # Clamp by the number we actually list — same reasoning as
    # generate_title. Also cap at 2 absolute: a 25-word lede can't
    # carry more than 2 entities without losing readability, regardless
    # of what SIE recommends.
    LEDE_ENTITY_CEILING = 2
    available = len(relevant_entities)
    effective_h1_target = min(h1_zone_target, available, LEDE_ENTITY_CEILING) if h1_zone_target > 0 else 0
    effective_h1_max = min(h1_zone_max if h1_zone_max > 0 else h1_zone_target, available, LEDE_ENTITY_CEILING) if h1_zone_target > 0 else 0
    if effective_h1_max and effective_h1_max < effective_h1_target:
        effective_h1_max = effective_h1_target
    if effective_h1_target > 0:
        entity_directive = (
            f"Entities to weave in (include at least {effective_h1_target}, "
            f"no more than {effective_h1_max}): {entity_list}"
        )
    else:
        entity_directive = (
            f"Entities to weave in (pick 1-2 most natural): {entity_list}"
        )
    user = (
        f"Topic: {h1_text}\n"
        f"Keyword to include or echo: {keyword}\n"
        f"{entity_directive}\n"
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
