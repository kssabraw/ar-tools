"""The media-planner LLM call: fill the prompt, get JSON, parse robustly, retry
once on parse failure. The model only proposes — validate.py enforces.
"""
from __future__ import annotations

import json
import logging
import re

from config import settings
from services.blog_media.planner_prompt import fill_prompt

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_plan_json(text: str) -> dict:
    """Parse the model's JSON, tolerating code fences / leading-trailing prose.
    Raises ValueError if no JSON object can be extracted. Pure."""
    if not text:
        raise ValueError("empty_plan_response")
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError("no_json_object_in_plan_response")


async def plan_media(
    *,
    article_title: str,
    article_html: str,
    article_plain_text: str,
    word_count: int,
    brand_personality: str,
) -> dict:
    """Run the media planner once (with a single JSON-parse retry). Returns the
    raw plan dict (unvalidated — the caller validates). Raises on total failure."""
    from services import report_llm

    prompt = fill_prompt(
        article_title=article_title,
        article_html=article_html,
        article_plain_text=article_plain_text,
        word_count=word_count,
        brand_personality=brand_personality,
        hero_width=settings.blog_media_hero_width,
        hero_height=settings.blog_media_hero_height,
        inline_width=settings.blog_media_inline_width,
        inline_height=settings.blog_media_inline_height,
        allow_derived=settings.blog_media_allow_derived_values,
    )
    system = (
        "You are a deterministic media-planning system. Return only the requested "
        "JSON object — no prose, no code fences."
    )

    raw = await report_llm.generate_text(
        provider="anthropic",
        model=settings.blog_media_planner_model,
        system=system,
        user=prompt,
        max_tokens=settings.blog_media_planner_max_tokens,
        log_tag="blog_media_plan",
    )
    try:
        return parse_plan_json(raw)
    except ValueError as exc:
        logger.warning("blog_media.plan_parse_retry", extra={"error": str(exc)})
        retry = await report_llm.generate_text(
            provider="anthropic",
            model=settings.blog_media_planner_model,
            system=system,
            user=(
                prompt
                + "\n\nYour previous response could not be parsed as JSON "
                f"({exc}). Return ONLY the JSON object, no code fences, no commentary."
            ),
            max_tokens=settings.blog_media_planner_max_tokens,
            log_tag="blog_media_plan_retry",
        )
        return parse_plan_json(retry)
