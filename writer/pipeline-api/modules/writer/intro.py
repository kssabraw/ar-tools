"""Step 5b — Intro writing (Writer v1.6 §4.3.1).

Single-paragraph Agree / Promise / Preview intro placed between H1 and the
first content H2. Three deterministic beats:
  - Agree:   1–2 sentences naming the reader's situation in their words.
  - Promise: 1 sentence anchored in the article's title + scope.
  - Preview: 1–2 sentences naming the first 3–5 H2 sections in order.

Hard constraints (per spec §4.3.1):
  - Exactly one paragraph (no blank-line breaks).
  - 60 ≤ word_count ≤ 150 (inclusive).
  - No heading markers (#, ##, …) and no list markers in the body.

Validation (per spec §4.3.2): word-count, single-paragraph, and no-heading
checks are post-hoc with single-retry; intro failures degrade to a
placeholder rather than aborting the run.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned

logger = logging.getLogger(__name__)


INTRO_MIN_WORDS = 60
INTRO_MAX_WORDS = 150
PREVIEW_H2_LIMIT = 5

_HEADING_MARKER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*+]\s|\d+[.)]\s)")


INTRO_SYSTEM = """You write the opening paragraph of a blog post.

OUTPUT FORMAT:
{"intro": "<single paragraph, 60-150 words>"}

WRITING RULES — Agree / Promise / Preview construction:
1. Agree (1-2 sentences) — name the reader's situation, problem, or curiosity in their own words.
2. Promise (1 sentence) — state what the article will deliver, anchored in the TITLE and SCOPE_STATEMENT.
3. Preview (1-2 sentences) — name the first 3-5 H2 sections the reader will encounter, in the order they appear.

HARD CONSTRAINTS:
- Exactly ONE paragraph. No blank lines. No line breaks inside the paragraph.
- 60 to 150 words total (inclusive).
- No headings, no bulleted or numbered lists, no markdown emphasis other than inline.
- Do not introduce out-of-scope topics.
- Do not include sales framing or company-specific positioning in the first 100 words.
- Do NOT use any FORBIDDEN_TERM.
- Match the BRAND_VOICE tone."""


def _build_intro_user_prompt(
    *,
    keyword: str,
    title: str,
    scope_statement: str,
    intent_type: str,
    h2_list: list[str],
    brand_voice_card: Optional[BrandVoiceCard],
    forbidden_terms: list[str],
    retry_directive: Optional[str],
) -> str:
    parts: list[str] = [
        f"KEYWORD: {keyword}",
        f"TITLE: {title}",
        f"INTENT: {intent_type}",
    ]
    if scope_statement:
        parts.append(f"SCOPE_STATEMENT: {scope_statement}")
    if h2_list:
        parts.append("\nH2_SECTIONS (preview the first 3-5 in order):")
        for idx, h2 in enumerate(h2_list[: PREVIEW_H2_LIMIT * 2], start=1):
            parts.append(f"  {idx}. {h2}")
    if brand_voice_card:
        if brand_voice_card.brand_name:
            parts.append(f"\nBRAND_NAME: {brand_voice_card.brand_name}")
            parts.append(
                "  You may mention the brand at most ONCE in the intro, and only when "
                "anchored to evidence (e.g., 'Ubiquitous campaign data shows ...'). Never "
                "as standalone promotion. Skipping the mention is acceptable when the "
                "topic is broad or when no concrete anchor fits naturally."
            )
        if brand_voice_card.tone_adjectives:
            parts.append(f"\nTONE: {', '.join(brand_voice_card.tone_adjectives)}")
        if brand_voice_card.voice_directives:
            parts.append(
                f"VOICE_DIRECTIVES: {' | '.join(brand_voice_card.voice_directives[:5])}"
            )
        if brand_voice_card.audience_summary:
            parts.append(f"\nAUDIENCE: {brand_voice_card.audience_summary}")
        if brand_voice_card.audience_personas:
            parts.append(f"  personas: {', '.join(brand_voice_card.audience_personas[:5])}")
        if brand_voice_card.audience_company_size:
            parts.append(f"  company size: {brand_voice_card.audience_company_size}")
        if brand_voice_card.audience_verticals:
            parts.append(
                f"  verticals: {', '.join(brand_voice_card.audience_verticals[:8])}"
            )
        if brand_voice_card.audience_pain_points:
            parts.append(
                f"  pain points: {', '.join(brand_voice_card.audience_pain_points[:3])}"
            )
        if brand_voice_card.audience_goals:
            parts.append(
                f"  goals (the Promise beat should advance one of these): "
                f"{', '.join(brand_voice_card.audience_goals[:3])}"
            )
    if forbidden_terms:
        parts.append(
            f"\nFORBIDDEN_TERMS: {', '.join(t.lower() for t in forbidden_terms[:30])}"
        )
    if retry_directive:
        parts.append(f"\nRETRY_DIRECTIVE: {retry_directive}")
    parts.append("\nWrite the JSON object with the intro field now.")
    return "\n".join(parts)


def _word_count(text: str) -> int:
    return len(text.split())


def _validate_intro(text: str) -> tuple[bool, Optional[str]]:
    """Return (ok, retry_directive). retry_directive is the one-line
    correction to feed into the retry prompt when ok is False."""
    if not text:
        return (False, "Previous attempt was empty. Write the intro now.")

    if "\n\n" in text.strip():
        return (
            False,
            "Previous attempt contained a paragraph break. Write a single "
            "paragraph with no blank lines and no line breaks inside it.",
        )

    if _HEADING_MARKER_RE.search(text):
        return (False, "Previous attempt contained a heading marker. Remove all # markers.")

    if _LIST_MARKER_RE.search(text):
        return (
            False,
            "Previous attempt contained a list marker. Write prose only — no "
            "bulleted or numbered lists.",
        )

    wc = _word_count(text)
    if wc < INTRO_MIN_WORDS:
        return (
            False,
            f"Previous attempt was {wc} words, too short. Expand to "
            f"{INTRO_MIN_WORDS}-{INTRO_MAX_WORDS} words.",
        )
    if wc > INTRO_MAX_WORDS:
        return (
            False,
            f"Previous attempt was {wc} words, too long. Trim to "
            f"{INTRO_MIN_WORDS}-{INTRO_MAX_WORDS} words while keeping all three beats.",
        )

    return (True, None)


def _normalize_intro(text: str) -> str:
    """Collapse any straggling whitespace into a clean single paragraph.
    Applied as a deterministic last-resort after retries to guarantee the
    single-paragraph rule."""
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    return collapsed


async def write_intro(
    *,
    keyword: str,
    title: str,
    scope_statement: str,
    intent_type: str,
    h2_list: list[str],
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    intro_order: int,
) -> ArticleSection:
    """One LLM call + at most one validation retry. Banned-term hits get
    their own retry per Section 4.4.3 (body-content rule). Validation
    failures after the retry degrade to a normalized accept-with-warning
    rather than aborting the run."""
    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    retry_directive: Optional[str] = None
    last_body: str = ""

    for attempt in range(2):
        user = _build_intro_user_prompt(
            keyword=keyword,
            title=title,
            scope_statement=scope_statement,
            intent_type=intent_type,
            h2_list=h2_list,
            brand_voice_card=brand_voice_card,
            forbidden_terms=forbidden_terms,
            retry_directive=retry_directive,
        )
        try:
            result = await claude_json(INTRO_SYSTEM, user, max_tokens=800, temperature=0.4)
        except Exception as exc:
            logger.warning("writer.intro.llm_failed", extra={"error": str(exc), "attempt": attempt + 1})
            return _placeholder_intro(intro_order)

        if not isinstance(result, dict):
            logger.warning("writer.intro.payload_not_dict", extra={"got_type": type(result).__name__})
            return _placeholder_intro(intro_order)

        body = (result.get("intro") or "").strip()
        last_body = body

        # Banned-term check first — same retry-then-abort policy as
        # body sections per Writer v1.5 §4.4.3.
        matches = find_banned(body, banned_regex)
        if matches and attempt == 0:
            retry_directive = (
                f"Previous attempt included forbidden term '{matches[0]}'. "
                f"Rewrite without it."
            )
            continue
        if matches and attempt == 1:
            raise BannedTermLeakage(
                term=matches[0],
                location="intro (after retry)",
                snippet=body[:120],
            )

        ok, validation_directive = _validate_intro(body)
        if ok:
            return ArticleSection(
                order=intro_order,
                level="none",
                type="intro",
                heading=None,
                body=body,
                word_count=_word_count(body),
                section_budget=INTRO_MAX_WORDS,
            )

        # Validation failed — retry once with the explicit directive.
        if attempt == 0:
            retry_directive = validation_directive
            continue

        # After-retry validation failure: log and accept the normalized body.
        logger.warning(
            "writer.intro.validation_failed_after_retry",
            extra={
                "directive": validation_directive,
                "word_count": _word_count(body),
                "had_paragraph_break": "\n\n" in body,
            },
        )
        normalized = _normalize_intro(body)
        return ArticleSection(
            order=intro_order,
            level="none",
            type="intro",
            heading=None,
            body=normalized,
            word_count=_word_count(normalized),
            section_budget=INTRO_MAX_WORDS,
        )

    # Loop fell through without returning (shouldn't happen) — emit what we have.
    if last_body:
        normalized = _normalize_intro(last_body)
        return ArticleSection(
            order=intro_order,
            level="none",
            type="intro",
            heading=None,
            body=normalized,
            word_count=_word_count(normalized),
            section_budget=INTRO_MAX_WORDS,
        )
    return _placeholder_intro(intro_order)


def _placeholder_intro(order: int) -> ArticleSection:
    return ArticleSection(
        order=order,
        level="none",
        type="intro",
        heading=None,
        body="[INTRO GENERATION FAILED — MANUAL REVIEW REQUIRED]",
        word_count=0,
    )
