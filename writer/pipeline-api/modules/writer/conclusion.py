"""Step 6 — Conclusion writing.

100-150 words. Synthesizes 2-3 sentence takeaway. Soft CTA per intent.
The seed keyword must appear at least once.

v1.5 (per spec §4.3): inject brand voice card heavily; use client services/
locations for natural references when website analysis was available; never
inject a hard sales CTA.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned

logger = logging.getLogger(__name__)


SOFT_CTA_BY_INTENT = {
    "how-to": "Following these steps will help readers make confident decisions.",
    "informational": "For more on the topic, readers can explore additional research.",
    "local-seo": "When choosing a service provider, consider what matters to you.",
    "ecom": "When choosing a product, consider what matters to your needs.",
    "informational-commercial": "When choosing among options, weigh the criteria that matter most.",
    "comparison": "When choosing between these options, focus on what aligns with your priorities.",
    "listicle": "Use this list as a starting point for further evaluation.",
    "news": "Stay informed by following authoritative sources for updates.",
}


CONCLUSION_SYSTEM = """You write a blog post conclusion.

OUTPUT FORMAT:
{"conclusion": "<conclusion prose, 100-150 words>"}

WRITING RULES:
- 100-150 words total.
- Synthesize the article's core takeaways in 2-3 sentences.
- End with a soft, generic call-to-action that fits the intent — never a hard sales CTA.
- Do not introduce new information not covered in the article.
- The seed keyword must appear at least once.
- Do NOT use any FORBIDDEN_TERM.
- Match the BRAND_VOICE tone."""


async def write_conclusion(
    keyword: str,
    intent_type: str,
    section_summaries: list[str],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    conclusion_order: int,
) -> ArticleSection:
    summary_block = "\n".join(f"  - {s}" for s in section_summaries[:8])
    soft_cta = SOFT_CTA_BY_INTENT.get(intent_type, SOFT_CTA_BY_INTENT["informational"])

    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    user_parts = [
        f"KEYWORD: {keyword}",
        f"INTENT: {intent_type}",
        f"\nSECTION_SUMMARIES (the article's main points — synthesize these):",
        summary_block,
        f"\nSOFT_CTA_DIRECTION: {soft_cta}",
    ]
    if brand_voice_card:
        if brand_voice_card.brand_name:
            user_parts.append(f"\nBRAND_NAME: {brand_voice_card.brand_name}")
            user_parts.append(
                "  The conclusion is the right place for ONE brand mention if it fits "
                "the closing argument — anchored to evidence or a specific service, "
                "never as a hard sales CTA. Skip if no natural anchor exists."
            )
        if brand_voice_card.tone_adjectives:
            user_parts.append(f"\nTONE: {', '.join(brand_voice_card.tone_adjectives)}")
        if brand_voice_card.voice_directives:
            user_parts.append(f"VOICE_DIRECTIVES: {' | '.join(brand_voice_card.voice_directives)}")
        if brand_voice_card.audience_summary:
            user_parts.append(f"\nAUDIENCE: {brand_voice_card.audience_summary}")
        if brand_voice_card.audience_personas:
            user_parts.append(f"  personas: {', '.join(brand_voice_card.audience_personas[:5])}")
        if brand_voice_card.audience_verticals:
            user_parts.append(f"  verticals: {', '.join(brand_voice_card.audience_verticals[:8])}")
        if brand_voice_card.audience_pain_points:
            user_parts.append(
                f"  pain points: {', '.join(brand_voice_card.audience_pain_points[:3])}"
            )
        if brand_voice_card.audience_goals:
            user_parts.append(
                f"  goals (the closing should reinforce one of these): "
                f"{', '.join(brand_voice_card.audience_goals[:3])}"
            )
        if brand_voice_card.client_services or brand_voice_card.client_locations:
            user_parts.append(
                "\nCLIENT_CONTEXT (reference one service or location if it naturally extends "
                "the closing point):"
            )
            if brand_voice_card.client_services:
                user_parts.append(f"  services: {', '.join(brand_voice_card.client_services[:5])}")
            if brand_voice_card.client_locations:
                user_parts.append(f"  locations: {', '.join(brand_voice_card.client_locations[:5])}")

    if forbidden_terms:
        user_parts.append(f"\nFORBIDDEN_TERMS: {', '.join(t.lower() for t in forbidden_terms)}")
    user_parts.append("\nWrite the JSON object with the conclusion field now.")
    user = "\n".join(user_parts)

    last_retry: Optional[str] = None
    for attempt in range(2):
        sys_prompt = CONCLUSION_SYSTEM
        if last_retry:
            sys_prompt += f"\n\nIMPORTANT: A previous attempt included the forbidden term '{last_retry}'. Rewrite without it."
        try:
            result = await claude_json(sys_prompt, user, max_tokens=600, temperature=0.4)
        except Exception as exc:
            logger.warning("Conclusion writing failed: %s", exc)
            return _placeholder_conclusion(conclusion_order)

        if not isinstance(result, dict):
            return _placeholder_conclusion(conclusion_order)
        body = (result.get("conclusion") or "").strip()
        if not body:
            return _placeholder_conclusion(conclusion_order)

        matches = find_banned(body, banned_regex)
        if matches and attempt == 0:
            last_retry = matches[0]
            continue
        if matches and attempt == 1:
            raise BannedTermLeakage(
                term=matches[0],
                location="conclusion (after retry)",
                snippet=body[:120],
            )

        return ArticleSection(
            order=conclusion_order,
            # Emit as H2 with an explicit "Conclusion" heading so the
            # rendered article carries a visible section break before
            # the wrap-up. Previously level="none" / heading=None ran
            # the conclusion as a free-floating prose block, which
            # readers experience as the body just trailing off.
            level="H2",
            type="conclusion",
            heading="Conclusion",
            body=body,
            word_count=len(body.split()),
            section_budget=125,
        )

    return _placeholder_conclusion(conclusion_order)


def _placeholder_conclusion(order: int) -> ArticleSection:
    return ArticleSection(
        order=order,
        level="H2",
        type="conclusion",
        heading="Conclusion",
        body="[CONCLUSION GENERATION FAILED — MANUAL REVIEW REQUIRED]",
        word_count=0,
    )
