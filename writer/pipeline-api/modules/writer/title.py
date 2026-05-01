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
) -> str:
    """Generate 3 candidates and pick the one with best keyword + entity coverage."""
    top_terms = required_terms[:8]
    top_entities = entities[:5]
    user = (
        f"Keyword: {keyword}\n"
        f"Intent: {intent_type}\n"
        f"Style: {_intent_guidance(intent_type)}\n"
        f"Required terms (incorporate where natural): {', '.join(top_terms) if top_terms else 'none'}\n"
        f"Entities (incorporate where natural): {', '.join(top_entities) if top_entities else 'none'}\n\n"
        "Write 3 distinct title candidates. Each must contain the seed keyword. "
        "Aim for keyword + entity coverage over brevity. Avoid promotional superlatives."
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
) -> str:
    """A 1-sentence lede (≤25 words) immediately after the H1.

    Must include 1-2 entities from categories: services, equipment, problems, methods.
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
    user = (
        f"Topic: {h1_text}\n"
        f"Keyword to include or echo: {keyword}\n"
        f"Entities to weave in (pick 1-2 most natural): {entity_list}\n"
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
