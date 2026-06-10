"""Step 6.5 - Key Takeaways generation (content-quality PRD §R4).

A bulleted list of 3-5 standalone sentences placed between H1 enrichment
and the APP intro. Optimized for AEO snippet capture: each bullet is a
self-contained, extractable claim from the article body.

Hard constraints:
  - 3 to 5 bullets total (let article depth determine; do not pad).
  - Each bullet <= 25 words (per PRD §R4).
  - One sentence per bullet.
  - Plain markdown bullets ("- "), no nested lists, no headings.

Validation: word-count + bullet-count checks are post-hoc with single
retry; failures degrade to a placeholder rather than aborting the run.
Generated AFTER body + conclusion + FAQ + intro so the prompt sees the
final article text and can summarize what was actually written.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned

logger = logging.getLogger(__name__)


KEY_TAKEAWAYS_MIN_BULLETS = 3
KEY_TAKEAWAYS_MAX_BULLETS = 5
KEY_TAKEAWAYS_MAX_WORDS_PER_BULLET = 25

_HEADING_MARKER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")


KEY_TAKEAWAYS_SYSTEM = """You extract Key Takeaways for the top of a blog post.

OUTPUT FORMAT:
{"key_takeaways": ["<sentence>", "<sentence>", ...]}

PURPOSE:
Key Takeaways sit at the top of the article, between the H1 and the intro. They give skimming readers the most important, extractable facts from the article. They are also optimized for AEO snippet capture, so each bullet must read as a standalone, quotable claim.

RULES:
- Return between 3 and 5 bullets. Let the article's depth determine the count - 3 if only 3 points are worth surfacing, 5 if the article is rich enough. Do not pad.
- Each bullet is ONE sentence, MAXIMUM 25 words.
- Each bullet summarizes one major point actually made in the article. Do not invent claims that are not in the article body.
- Bullets must be standalone - a reader must understand each bullet without context from the article.
- Prioritize actionable, specific, and concrete points. Skip introductory, transitional, or obvious statements.
- Plain, confident language. No fluff, no filler ("it's important to remember that", "as we discussed", etc.).
- Bullets must be distinct - do not repeat the same idea in different words.
- Do not reference the article ("this article shows", "as shown above", "below we cover").
- Do NOT use any FORBIDDEN_TERM.
- Do not use em dashes. Use a plain hyphen (-) instead.
- Match the BRAND_VOICE tone."""


def _build_key_takeaways_user_prompt(
    *,
    keyword: str,
    intent_type: str,
    article_body: str,
    brand_voice_card: Optional[BrandVoiceCard],
    forbidden_terms: list[str],
    retry_directive: Optional[str],
) -> str:
    parts: list[str] = [
        f"KEYWORD: {keyword}",
        f"INTENT: {intent_type}",
    ]

    if brand_voice_card:
        if brand_voice_card.tone_adjectives:
            parts.append(
                f"\nBRAND_VOICE (every bullet should read as): "
                f"{', '.join(brand_voice_card.tone_adjectives)}"
            )
        if brand_voice_card.voice_directives:
            parts.append(
                f"VOICE_DIRECTIVES: "
                f"{' | '.join(brand_voice_card.voice_directives[:3])}"
            )
        if brand_voice_card.preferred_terms:
            parts.append(
                f"FAVORED_PHRASING (use naturally where they fit): "
                f"{', '.join(brand_voice_card.preferred_terms[:15])}"
            )
        if brand_voice_card.discouraged_terms:
            parts.append(
                f"DISCOURAGED (avoid where possible): "
                f"{', '.join(brand_voice_card.discouraged_terms[:10])}"
            )

    if forbidden_terms:
        parts.append(
            f"\nFORBIDDEN_TERMS: {', '.join(t.lower() for t in forbidden_terms[:30])}"
        )

    parts.append(
        f"\nARTICLE_BODY (this is the source text - all bullets must reflect "
        f"claims actually made here):\n{article_body}"
    )

    if retry_directive:
        parts.append(f"\nRETRY_DIRECTIVE: {retry_directive}")

    parts.append(
        "\nWrite the JSON object now. Return 3-5 bullets, each one sentence, "
        "each <= 25 words, each a distinct extractable claim."
    )
    return "\n".join(parts)


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _validate_bullets(bullets: list[str]) -> tuple[bool, Optional[str]]:
    """Return (ok, retry_directive). retry_directive is the correction to
    feed back to the LLM when ok is False."""
    if not bullets:
        return False, "Previous attempt returned no bullets. Return 3-5 bullets now."

    if len(bullets) < KEY_TAKEAWAYS_MIN_BULLETS:
        return (
            False,
            f"Previous attempt returned only {len(bullets)} bullets. Return at "
            f"least {KEY_TAKEAWAYS_MIN_BULLETS} bullets.",
        )

    if len(bullets) > KEY_TAKEAWAYS_MAX_BULLETS:
        return (
            False,
            f"Previous attempt returned {len(bullets)} bullets. Return at most "
            f"{KEY_TAKEAWAYS_MAX_BULLETS} bullets.",
        )

    for idx, bullet in enumerate(bullets, start=1):
        text = bullet.strip()
        if not text:
            return False, f"Bullet {idx} was empty. Return non-empty bullets only."

        wc = _word_count(text)
        if wc > KEY_TAKEAWAYS_MAX_WORDS_PER_BULLET:
            return (
                False,
                f"Bullet {idx} was {wc} words (max "
                f"{KEY_TAKEAWAYS_MAX_WORDS_PER_BULLET}). Shorten it.",
            )

        if _HEADING_MARKER_RE.search(text):
            return False, f"Bullet {idx} contained a heading marker (#). Remove it."

    seen_lower: set[str] = set()
    for idx, bullet in enumerate(bullets, start=1):
        key = bullet.strip().lower()
        if key in seen_lower:
            return (
                False,
                f"Bullet {idx} duplicates a previous bullet. Each bullet must be distinct.",
            )
        seen_lower.add(key)

    return True, None


def _format_body(bullets: list[str]) -> str:
    return "\n".join(f"- {b.strip()}" for b in bullets)


async def write_key_takeaways(
    *,
    keyword: str,
    intent_type: str,
    article_body: str,
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    key_takeaways_order: int,
) -> ArticleSection:
    """One LLM call + at most one validation retry. Banned-term hits get
    their own retry. Validation failures after the retry degrade to an
    accept-with-warning rather than aborting the run."""
    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    retry_directive: Optional[str] = None
    last_bullets: Optional[list[str]] = None

    for attempt in range(2):
        user = _build_key_takeaways_user_prompt(
            keyword=keyword,
            intent_type=intent_type,
            article_body=article_body,
            brand_voice_card=brand_voice_card,
            forbidden_terms=forbidden_terms,
            retry_directive=retry_directive,
        )

        try:
            result = await claude_json(KEY_TAKEAWAYS_SYSTEM, user, max_tokens=800, temperature=0.3)
        except Exception as exc:
            logger.warning(
                "writer.key_takeaways.llm_failed",
                extra={"error": str(exc), "attempt": attempt + 1},
            )
            return _placeholder_key_takeaways(key_takeaways_order)

        if not isinstance(result, dict):
            logger.warning(
                "writer.key_takeaways.payload_not_dict",
                extra={"got_type": type(result).__name__},
            )
            return _placeholder_key_takeaways(key_takeaways_order)

        raw_bullets = result.get("key_takeaways") or []
        if not isinstance(raw_bullets, list):
            if attempt == 0:
                retry_directive = (
                    "Previous attempt's `key_takeaways` field was not a list. "
                    "Return a JSON list of 3-5 sentence strings."
                )
                continue
            return _placeholder_key_takeaways(key_takeaways_order)

        bullets = [str(b).strip() for b in raw_bullets if isinstance(b, (str, int, float)) and not isinstance(b, bool) and str(b).strip()]
        last_bullets = bullets
        body = _format_body(bullets)

        matches = find_banned(body, banned_regex)
        if matches and attempt == 0:
            retry_directive = (
                f"Previous attempt included forbidden term '{matches[0]}'. "
                f"Rewrite all bullets without it."
            )
            continue
        if matches and attempt == 1:
            raise BannedTermLeakage(
                term=matches[0],
                location="key_takeaways (after retry)",
                snippet=body[:120],
            )

        ok, validation_directive = _validate_bullets(bullets)
        if ok:
            logger.info(
                "writer.key_takeaways.complete",
                extra={"bullet_count": len(bullets), "word_count": _word_count(body)},
            )
            return ArticleSection(
                order=key_takeaways_order,
                level="none",
                type="key-takeaways",
                heading="Key Takeaways",
                body=body,
                word_count=_word_count(body),
            )

        if attempt == 0:
            retry_directive = validation_directive
            continue

        logger.warning(
            "writer.key_takeaways.validation_failed_after_retry",
            extra={
                "directive": validation_directive,
                "bullet_count": len(bullets),
            },
        )
        return ArticleSection(
            order=key_takeaways_order,
            level="none",
            type="key-takeaways",
            heading="Key Takeaways",
            body=body,
            word_count=_word_count(body),
        )

    if last_bullets:
        body = _format_body(last_bullets)
        return ArticleSection(
            order=key_takeaways_order,
            level="none",
            type="key-takeaways",
            heading="Key Takeaways",
            body=body,
            word_count=_word_count(body),
        )
    return _placeholder_key_takeaways(key_takeaways_order)


def _placeholder_key_takeaways(order: int) -> ArticleSection:
    return ArticleSection(
        order=order,
        level="none",
        type="key-takeaways",
        heading="Key Takeaways",
        body="[KEY TAKEAWAYS GENERATION FAILED - MANUAL REVIEW REQUIRED]",
        word_count=0,
    )
