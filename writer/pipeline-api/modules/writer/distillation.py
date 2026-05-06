"""Step 3.5a - Brand Voice Distillation.

Single Claude call. Compresses brand_guide_text + icp_text + (optional)
website_analysis into a structured BrandVoiceCard. Tone signals come ONLY
from brand_guide_text - website_analysis provides factual reference data
(services, locations, contact_info) only.

Categorization-only: never invent banned/preferred terms.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.writer import BrandVoiceCard, ClientContactInfo, ClientContextInput

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


DISTILLATION_SYSTEM = """You are a categorization-only LLM. Your job is to extract and summarize brand voice signals from the provided source documents - never to infer brand opinions that are not stated.

You must output a single JSON object matching this exact schema:
{
  "brand_name": string (the actual brand/company name, e.g. "Ubiquitous", "Acme Co"; empty string if not stated),
  "tone_adjectives": [string],
  "voice_directives": [string, max 200 chars each, max 8 items],
  "audience_summary": string (max 300 chars),
  "audience_personas": [string, max 8 items - job titles or roles the ICP names, e.g. "VP of Growth", "CMO", "Director of Marketing"],
  "audience_verticals": [string, max 12 items - industry verticals or categories the ICP targets, e.g. "Beauty", "Health & Wellness", "Pet Care"],
  "audience_company_size": string (max 120 chars - the company-size descriptor the ICP uses, e.g. "$20M+ ARR (sweet spot $30M–$100M)"),
  "audience_pain_points": [string, max 5 items],
  "audience_goals": [string, max 5 items],
  "preferred_terms": [string, max 20 items],
  "banned_terms": [string, max 30 items],
  "discouraged_terms": [string, max 20 items],
  "client_services": [string, max 15 items],
  "client_locations": [string, max 15 items],
  "client_contact_info": {"phone": string|null, "email": string|null, "address": string|null, "hours": string|null}
}

CRITICAL RULES:
- brand_name is the proper noun the brand uses for itself in the brand guide. Extract it verbatim - do NOT paraphrase or expand acronyms. If the brand guide does not state a name, return "".
- tone_adjectives and voice_directives come ONLY from the brand guide text. NEVER from website analysis.
- A term is "banned" ONLY when the brand guide uses literal prohibitive language about it: "never use", "do not use", "DO NOT", "banned", "prohibited", "must not appear", "absolute no", or equivalent. The bar is HIGH - banned means the writer must error if the term appears.
- A term is "discouraged" when the brand guide expresses any softer preference against it - "avoid", "we prefer X over Y", "try not to use", "lean away from", "use sparingly", "minimize", or any preference-without-prohibition language. When in doubt between banned and discouraged, classify as discouraged.
- A term is "preferred" when the brand guide names it as preferred phrasing.
- audience_summary, audience_personas, audience_verticals, audience_company_size, audience_pain_points, audience_goals all come from the ICP text.
- audience_personas: extract the named job titles/roles verbatim (e.g. "VP of Growth", "Director of Marketing"). Do not infer titles that aren't in the ICP.
- audience_verticals: extract the named industry verticals verbatim (e.g. "Beauty", "Food & Beverage"). Do not infer verticals that aren't in the ICP.
- audience_company_size: extract the literal company-size descriptor (revenue band, employee count, growth stage, etc.). Empty string if the ICP doesn't specify.
- client_services, client_locations, client_contact_info come ONLY from website analysis (verbatim).
- If a field has no information in the source, return an empty array, empty string, or null.
- Never invent. If brand guide does not mention term-level guidance, return empty arrays for the term lists."""


def _build_user_prompt(ctx: ClientContextInput) -> str:
    parts = []
    parts.append("=== BRAND GUIDE TEXT ===")
    parts.append(ctx.brand_guide_text or "(empty)")
    parts.append("\n=== ICP (IDEAL CUSTOMER PROFILE) TEXT ===")
    parts.append(ctx.icp_text or "(empty)")
    if not ctx.website_analysis_unavailable and ctx.website_analysis:
        parts.append("\n=== WEBSITE ANALYSIS (factual reference only - services, locations, contact_info) ===")
        wa = ctx.website_analysis
        parts.append(f"services: {wa.get('services', [])}")
        parts.append(f"locations: {wa.get('locations', [])}")
        parts.append(f"contact_info: {wa.get('contact_info', {})}")
    parts.append("\nDistill into the brand voice card JSON object now.")
    return "\n".join(parts)


def _truncate(text: str, max_chars: int = 100_000) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"


async def distill_brand_voice(ctx: ClientContextInput) -> Optional[BrandVoiceCard]:
    """Returns BrandVoiceCard or None on hard failure (caller decides).

    Never raises. Logs warnings on partial failures.
    """
    safe_ctx = ClientContextInput(
        brand_guide_text=_truncate(ctx.brand_guide_text),
        icp_text=_truncate(ctx.icp_text),
        website_analysis=ctx.website_analysis,
        website_analysis_unavailable=ctx.website_analysis_unavailable,
    )

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        system = DISTILLATION_SYSTEM
        if attempt > 0:
            system += "\n\nIMPORTANT: Your previous response did not parse as valid JSON. Return ONLY the JSON object."
        try:
            result = await claude_json(
                system=system,
                user=_build_user_prompt(safe_ctx),
                max_tokens=2500,
                temperature=0.1,
            )
            if not isinstance(result, dict):
                raise ValueError("expected JSON object")
            return _parse_card(result)
        except Exception as exc:
            last_exc = exc
            logger.warning("Brand distillation attempt %d failed: %s", attempt + 1, exc)
    logger.error("Brand distillation gave up: %s", last_exc)
    return None


def _parse_card(raw: dict) -> BrandVoiceCard:
    """Parse a raw dict into a BrandVoiceCard, applying safe defaults + caps."""
    def _list(key: str, cap: int) -> list[str]:
        v = raw.get(key) or []
        if not isinstance(v, list):
            return []
        return [str(x).strip()[:200] for x in v if x][:cap]

    contact_raw = raw.get("client_contact_info") or {}
    if not isinstance(contact_raw, dict):
        contact_raw = {}

    return BrandVoiceCard(
        brand_name=str(raw.get("brand_name") or "").strip()[:120],
        tone_adjectives=_list("tone_adjectives", 12),
        voice_directives=_list("voice_directives", 8),
        audience_summary=str(raw.get("audience_summary") or "")[:300],
        audience_personas=_list("audience_personas", 8),
        audience_verticals=_list("audience_verticals", 12),
        audience_company_size=str(raw.get("audience_company_size") or "").strip()[:120],
        audience_pain_points=_list("audience_pain_points", 5),
        audience_goals=_list("audience_goals", 5),
        preferred_terms=_list("preferred_terms", 20),
        banned_terms=_list("banned_terms", 30),
        discouraged_terms=_list("discouraged_terms", 20),
        client_services=_list("client_services", 15),
        client_locations=_list("client_locations", 15),
        client_contact_info=ClientContactInfo(
            phone=contact_raw.get("phone"),
            email=contact_raw.get("email"),
            address=contact_raw.get("address"),
            hours=contact_raw.get("hours"),
        ),
    )


def is_card_empty(card: Optional[BrandVoiceCard]) -> bool:
    if card is None:
        return True
    return not any([
        card.brand_name,
        card.tone_adjectives, card.voice_directives,
        card.audience_summary, card.audience_personas,
        card.audience_verticals, card.audience_company_size,
        card.audience_pain_points, card.audience_goals,
        card.preferred_terms, card.banned_terms, card.discouraged_terms,
        card.client_services, card.client_locations,
    ])
