"""Step 2.5 - Intro writing.

A single free-form opening intro placed between H1 (and the Key Takeaways
block) and the first content H2. The intro is written entirely in the
client's brand voice and grounded in the ICP/audience context - there is
no fixed beat structure.

(Historical note: earlier versions used an "APP" framework - Agree /
Promise / Preview - with a menu of opening styles. That rigid structure
was dropped per user decision; the intro is now brand-voice + ICP driven.
See content-quality-prd-v1_0.md R4.)

Hard constraints:
  - 80 <= total_word_count <= 120 (inclusive).
  - No heading markers (#, ##, ...) and no list markers.
  - Prose only - no roadmap enumeration of the article's H2s.

Validation: word-count and format checks are post-hoc with a single
retry; intro failures degrade to a placeholder rather than aborting the
run.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned

logger = logging.getLogger(__name__)


INTRO_MIN_WORDS = 80
INTRO_MAX_WORDS = 120

_HEADING_MARKER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*+]\s|\d+[.)]\s)")


INTRO_SYSTEM = """You write the opening intro for a blog post.

OUTPUT FORMAT:
{"intro": "<text>"}

WHAT THE INTRO DOES:
- START with ONE sentence that directly and completely answers the query (the KEYWORD), written so it can be lifted verbatim into a search snippet / AI Overview: a confident declarative statement, self-contained (no "this article", no pronouns pointing outside the sentence), roughly 15-30 words. Ground this answer in ANSWER_CONTEXT and SUPPORTING_DATA when provided - never invent facts or contradict the article's scope.
- THEN continue with a short brand-voice opener (1 short paragraph) that meets the reader where they are and pulls them forward.
- Write entirely in the BRAND_VOICE. The tone adjectives and voice directives are not optional - every sentence should sound like the brand (the answer sentence included; it should be direct AND on-voice).
- When AUDIENCE context is provided, ground the opener in the audience's specific situation, pain points, and language. Do not write generically when ICP context is available.

LENGTH: 80-120 words total. Write it as 1-2 short paragraphs, the first of which opens with the direct answer sentence.

HARD CONSTRAINTS:
- No heading markers (#, ##, etc.), no bullets, no numbered lists.
- Do NOT enumerate the article's sections or write an ordered roadmap ("You'll start with X, move into Y, then Z" or any variation). The intro should create momentum, not summarize structure.
- Do not introduce topics outside the article's scope.
- No sales framing or hard CTA language.
- Do NOT use any FORBIDDEN_TERM.
- Do not use em dashes. Use a plain hyphen (-) instead.
- Keep paragraphs to 4 sentences or fewer."""


def _build_intro_user_prompt(
    *,
    keyword: str,
    title: str,
    scope_statement: str,
    intent_type: str,
    h2_list: list[str],
    brand_voice_card: Optional[BrandVoiceCard],
    forbidden_terms: list[str],
    supporting_data: Optional[str],
    answer_context: Optional[str],
    retry_directive: Optional[str],
    reference_structure: Optional[str] = None,
) -> str:
    parts: list[str] = [
        f"KEYWORD: {keyword}",
        f"TITLE: {title}",
        f"INTENT: {intent_type}",
    ]
    if scope_statement:
        parts.append(f"SCOPE_STATEMENT: {scope_statement}")

    # Optional: mirror how this client opens their own blog posts. The blog
    # brief is client-agnostic + globally cached, so the heading structure can't
    # carry the client's layout; the intro honors the opening pattern here. The
    # block is already opening-scoped (rendered with mode="opening") — pass it
    # through under a clear header.
    if reference_structure and reference_structure.strip():
        parts.append("")  # blank line before the block
        parts.append(reference_structure.strip())

    # Grounding for the opening direct-answer sentence: a digest of what the
    # article actually says (section summaries), so the liftable answer can't
    # drift from the body. The intro is generated after the body exists.
    if answer_context:
        parts.append(
            "\nANSWER_CONTEXT (what the article establishes - base the opening "
            "answer sentence on this; do not contradict it):"
        )
        parts.append(answer_context)

    # ICP / audience context - grounds the intro in the audience's
    # situation. Pulled from the distilled brand voice card, which encodes
    # client_context.icp_text.
    if brand_voice_card:
        audience_parts: list[str] = []
        if brand_voice_card.audience_summary:
            audience_parts.append(brand_voice_card.audience_summary)
        if brand_voice_card.audience_personas:
            audience_parts.append(f"personas: {', '.join(brand_voice_card.audience_personas[:5])}")
        if brand_voice_card.audience_company_size:
            audience_parts.append(f"company size: {brand_voice_card.audience_company_size}")
        if brand_voice_card.audience_verticals:
            audience_parts.append(f"verticals: {', '.join(brand_voice_card.audience_verticals[:6])}")
        if brand_voice_card.audience_pain_points:
            audience_parts.append(
                f"pain points (ground the opening here): "
                f"{', '.join(brand_voice_card.audience_pain_points[:3])}"
            )
        if brand_voice_card.audience_goals:
            audience_parts.append(
                f"goals (the intro should hint at advancing one of these): "
                f"{', '.join(brand_voice_card.audience_goals[:3])}"
            )
        if audience_parts:
            parts.append("\nAUDIENCE:")
            parts.extend(f"  {p}" for p in audience_parts)

    # Supporting data - the intro may anchor on a concrete stat where it
    # strengthens the opening, but must not fabricate one.
    if supporting_data:
        parts.append(f"\nSUPPORTING_DATA (use only if it strengthens the opening; never fabricate): {supporting_data}")

    # Article topic context - helps the LLM understand the article's scope.
    # Must NOT be enumerated as a roadmap in the intro.
    if h2_list:
        parts.append("\nARTICLE_TOPICS (context only - do NOT enumerate these in the intro):")
        for h2 in h2_list[:8]:
            parts.append(f"  - {h2}")

    if brand_voice_card:
        if brand_voice_card.brand_name:
            parts.append(f"\nBRAND_NAME: {brand_voice_card.brand_name}")
        if brand_voice_card.tone_adjectives:
            parts.append(
                f"BRAND_VOICE (every sentence should read as): "
                f"{', '.join(brand_voice_card.tone_adjectives)}"
            )
        if brand_voice_card.voice_directives:
            parts.append(
                f"VOICE_DIRECTIVES: "
                f"{' | '.join(brand_voice_card.voice_directives[:5])}"
            )
        if brand_voice_card.preferred_terms:
            parts.append(
                f"FAVORED_PHRASING (use naturally where they fit): "
                f"{', '.join(brand_voice_card.preferred_terms[:15])}"
            )
        if brand_voice_card.discouraged_terms:
            parts.append(
                f"DISCOURAGED (avoid where possible - softer than forbidden): "
                f"{', '.join(brand_voice_card.discouraged_terms[:10])}"
            )

    if forbidden_terms:
        parts.append(
            f"\nFORBIDDEN_TERMS: {', '.join(t.lower() for t in forbidden_terms[:30])}"
        )
    if retry_directive:
        parts.append(f"\nRETRY_DIRECTIVE: {retry_directive}")
    parts.append("\nWrite the JSON object now.")
    return "\n".join(parts)


def _word_count(text: str) -> int:
    return len(text.split())


def _validate_intro(body: str) -> tuple[bool, Optional[str]]:
    """Return (ok, retry_directive). retry_directive is the correction to
    feed into the retry prompt when ok is False."""
    if not body.strip():
        return False, "Previous attempt: 'intro' was empty. Write it now."

    total = _word_count(body)
    if total < INTRO_MIN_WORDS:
        return (
            False,
            f"Previous attempt was {total} words total, too short. Expand to "
            f"{INTRO_MIN_WORDS}-{INTRO_MAX_WORDS} words.",
        )
    if total > INTRO_MAX_WORDS:
        return (
            False,
            f"Previous attempt was {total} words total, too long. Trim to "
            f"{INTRO_MIN_WORDS}-{INTRO_MAX_WORDS} words.",
        )

    if _HEADING_MARKER_RE.search(body):
        return False, "Previous attempt contained heading markers (#). Remove all # markers."
    if _LIST_MARKER_RE.search(body):
        return (
            False,
            "Previous attempt contained list markers. Write prose only - no "
            "bulleted or numbered lists.",
        )

    return True, None


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
    supporting_data: Optional[str] = None,
    answer_context: Optional[str] = None,
    reference_structure: Optional[str] = None,
) -> ArticleSection:
    """One LLM call + at most one validation retry. Banned-term hits get
    their own retry per Section 4.4.3. Validation failures after the retry
    degrade to an accept-with-warning rather than aborting the run."""
    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    retry_directive: Optional[str] = None
    last_body: Optional[str] = None

    for attempt in range(2):
        user = _build_intro_user_prompt(
            keyword=keyword,
            title=title,
            scope_statement=scope_statement,
            intent_type=intent_type,
            h2_list=h2_list,
            brand_voice_card=brand_voice_card,
            forbidden_terms=forbidden_terms,
            supporting_data=supporting_data,
            answer_context=answer_context,
            retry_directive=retry_directive,
            reference_structure=reference_structure,
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

        if not body:
            if attempt == 0:
                retry_directive = (
                    "Previous attempt was missing the required 'intro' field. "
                    "Return it now."
                )
                continue
            return _placeholder_intro(intro_order)

        last_body = body

        # Banned-term check - same retry-then-abort policy as body sections
        # per Writer v1.5 §4.4.3.
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
            logger.info(
                "writer.intro.complete",
                extra={"word_count": _word_count(body)},
            )
            return ArticleSection(
                order=intro_order,
                level="none",
                type="intro",
                heading=None,
                body=body,
                word_count=_word_count(body),
                section_budget=INTRO_MAX_WORDS,
            )

        if attempt == 0:
            retry_directive = validation_directive
            continue

        # After-retry validation failure: log and accept.
        logger.warning(
            "writer.intro.validation_failed_after_retry",
            extra={
                "directive": validation_directive,
                "word_count": _word_count(body),
            },
        )
        return ArticleSection(
            order=intro_order,
            level="none",
            type="intro",
            heading=None,
            body=body,
            word_count=_word_count(body),
            section_budget=INTRO_MAX_WORDS,
        )

    if last_body:
        return ArticleSection(
            order=intro_order,
            level="none",
            type="intro",
            heading=None,
            body=last_body,
            word_count=_word_count(last_body),
            section_budget=INTRO_MAX_WORDS,
        )
    return _placeholder_intro(intro_order)


def _placeholder_intro(order: int) -> ArticleSection:
    return ArticleSection(
        order=order,
        level="none",
        type="intro",
        heading=None,
        body="[INTRO GENERATION FAILED - MANUAL REVIEW REQUIRED]",
        word_count=0,
    )
