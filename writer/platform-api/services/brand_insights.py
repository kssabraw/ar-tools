"""AI Visibility — auxiliary OpenAI features: invisibility diagnosis and
keyword suggestions. Both are on-demand (not per-scan-row), so they use the
latest OpenAI flagship. Prompts ported from brand-strength-ai's
diagnose-invisibility / suggest-keywords edge functions.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from config import settings


class InsightUnavailable(Exception):
    """OpenAI isn't configured or the call failed irrecoverably."""


def _client():
    if not settings.openai_api_key:
        raise InsightUnavailable("openai_not_configured")
    import openai

    return openai.AsyncOpenAI(api_key=settings.openai_api_key)


def _diagnosis_prompt(brand: str, keyword: str, raw_response: str) -> str:
    return (
        f'The brand "{brand}" was searched for using the query "{keyword}" but was '
        f"NOT found in the results.\n\nHere are the businesses that WERE found:\n"
        f'"""\n{(raw_response or "")[:4000]}\n"""\n\n'
        f'Analyze why "{brand}" might be invisible to this AI search and provide:\n'
        "1. What types of businesses ARE appearing (and why they likely rank)\n"
        "2. Specific reasons this brand might be missing (weak SEO, no reviews, no listings, etc.)\n"
        "3. 2-3 actionable steps to improve AI visibility for this specific query\n\n"
        "Be specific and reference the actual competitors shown. Keep the response "
        "concise (under 250 words). Format with clear sections."
    )


async def diagnose_invisibility(brand: str, keyword: str, raw_response: str) -> str:
    client = _client()
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_diagnose_model,
            messages=[
                {"role": "system", "content": "You are a local SEO and AI Answer Engine Optimization expert."},
                {"role": "user", "content": _diagnosis_prompt(brand, keyword, raw_response)},
            ],
        )
    except Exception as exc:  # pragma: no cover - thin provider wrapper
        raise InsightUnavailable(str(exc))
    return (resp.choices[0].message.content or "").strip()


def _suggest_prompt(brand: str, business_types: list[str], address: Optional[str]) -> str:
    type_ctx = f"Business types: {', '.join(business_types)}." if business_types else ""
    loc_ctx = f"Located at: {address}." if address else ""
    return (
        "You are an expert at local SEO and AI Answer Engine Optimization. Generate "
        "exactly 5 high-intent search keywords that potential customers would use to "
        "find this business through AI assistants like ChatGPT, Gemini, or Perplexity.\n\n"
        f"Business name: {brand}\n{type_ctx}\n{loc_ctx}\n\n"
        "Requirements:\n"
        '- Focus on local/service-intent keywords (e.g., "plumber near me", "emergency AC repair")\n'
        f'- Include the business name in at least one keyword (e.g., "{brand} reviews")\n'
        "- Make keywords specific to the business type, not generic\n"
        "- Keywords should be what someone would ask an AI assistant\n"
        "- Return ONLY a JSON array of 5 strings, nothing else"
    )


def _parse_keyword_list(text: str) -> list[str]:
    """Pull a JSON array of strings out of the model's reply, tolerating fences."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(k).strip() for k in data if isinstance(k, (str, int)) and str(k).strip()][:5]


async def suggest_keywords(brand: str, business_types: list[str], address: Optional[str]) -> list[str]:
    client = _client()
    try:
        resp = await client.chat.completions.create(
            model=settings.brand_suggest_model,
            messages=[
                {"role": "system", "content": "You are a local SEO expert. Return only valid JSON arrays."},
                {"role": "user", "content": _suggest_prompt(brand, business_types, address)},
            ],
        )
    except Exception as exc:  # pragma: no cover
        raise InsightUnavailable(str(exc))
    return _parse_keyword_list(resp.choices[0].message.content or "")
