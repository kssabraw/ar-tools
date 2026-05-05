"""Step 2.5 — Intro writing (Writer v1.6 §4.3.1).

Three-beat Agree / Promise / Preview intro placed between H1 and the
first content H2. Each beat is a discrete prose block:
  - Agree:   2–3 sentences grounding the reader's situation. The LLM
              selects the best Agree style from 10 options based on
              topic, ICP audience context, and supporting data.
  - Promise: 1 sentence stating what the article will deliver.
  - Preview: 1 sentence creating curiosity or momentum — no topic
              enumeration, no ordered roadmap.

Hard constraints:
  - 80 ≤ total_word_count ≤ 120 (inclusive).
  - Each block ≤ 50 words.
  - No heading markers (#, ##, …) and no list markers in any block.

Validation (per spec §4.3.2): word-count and format checks are post-hoc
with single retry; intro failures degrade to a placeholder rather than
aborting the run.
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
INTRO_MAX_WORDS_PER_BLOCK = 50

_HEADING_MARKER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*+]\s|\d+[.)]\s)")


INTRO_SYSTEM = """You write the opening intro for a blog post using the APP framework: Agree, Promise, Preview.

OUTPUT FORMAT:
{"agree_style_selected": "<style name>", "agree": "<text>", "promise": "<text>", "preview": "<text>"}

THE THREE BEATS:

1. Agree — Meet the reader where they are. Validate a frustration, feeling, or belief they already hold.
   - When AUDIENCE context is provided, ground it in the audience's specific situation, pain points, or language. Do not write generically when ICP context is available.
   - 2–3 sentences maximum.
   - Select the best Agree style from the list below.

2. Promise — One sentence. Specific, concrete commitment about what this article delivers.
   - No vague language like "we'll cover everything you need to know."

3. Preview — One sentence. Create curiosity or momentum.
   - Do NOT enumerate topics or write an ordered roadmap ("You'll start with X, move into Y, then Z" or any variation).
   - The sentence should pull the reader forward, not summarize structure.

TOTAL LENGTH: 80–120 words across all three beats combined. Each individual beat ≤ 50 words.

AGREE STYLES — select the single best style given the topic, audience, and data:

⚠️ HALLUCINATION WARNING: `data_led` and `research_reframe` require real numbers or studies. Only select these styles when SUPPORTING_DATA is provided. If either would be best but no data is available, select the next most appropriate style instead.

counterintuitive_claim — Opens with a statement that flips conventional wisdom. Use when a widely-held belief is demonstrably wrong. Example: "Doing more of the same thing rarely produces different results."
false_solution — Names an approach everyone uses, then immediately undercuts it. Use when the audience is invested in a popular but ineffective method. Example: "Tracking activity feels like measuring progress. It usually isn't."
failure_mode — Leads with the mistake the reader is probably making, or the cost of the unchanged status quo. Example: "The instinct is to add more. That's often exactly what slows things down."
data_led — Anchors with a specific number or average-vs-top-performer comparison. Requires SUPPORTING_DATA. Example: "Most teams hit their targets roughly half the time. High performers hit them consistently."
research_reframe — References a study or trend that recontextualizes the problem. Requires SUPPORTING_DATA. Example: "Recent data shows buyers decide earlier in the process than most teams assume — yet most content is built for the wrong stage."
scene_setting — Drops into a specific, recognizable moment — third person or no person. Example: "The work gets done. The results meeting doesn't reflect it."
before_after — Contrasts two states with tension and resolution implied, no roadmap. Example: "Inconsistent results aren't a strategy problem. They're an execution problem. And execution problems have repeatable fixes."
core_distinction — Opens by drawing a line between two things the audience conflates. Example: "There's a difference between being busy and making progress. Most teams are optimizing for the wrong one."
reframe_the_question — Suggests the reader has been asking the wrong question. Example: "The question isn't whether the approach works. It's whether you're set up to see it working."
direct_thesis — Plain, confident statement of exactly what's true and what this piece proves. Use as the fallback when no other style fits cleanly. Example: "This is solvable, repeatable, and measurable. Here's how to get there."

STYLE SELECTION CRITERIA (apply in order):
1. If SUPPORTING_DATA is provided and a specific stat or study would strengthen the Agree, prefer data_led or research_reframe.
2. If AUDIENCE context is provided, match the style to the audience's stated pain points or goals. Practitioners often respond to failure_mode or false_solution; decision-makers to data_led or reframe_the_question.
3. Choose based on topic shape: a commonly-held wrong belief → counterintuitive_claim; a measurement or methodology topic → core_distinction; a definitional "what is X" topic → direct_thesis.
4. If no style fits cleanly or would produce an awkward or misleading Agree, use direct_thesis.

HARD CONSTRAINTS:
- No heading markers (#, ##, etc.), no bullets, no numbered lists in any block.
- Do not introduce topics outside the article's scope.
- No sales framing or hard CTA language in any beat.
- Do NOT use any FORBIDDEN_TERM.
- Match the BRAND_VOICE tone throughout."""


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
    retry_directive: Optional[str],
) -> str:
    parts: list[str] = [
        f"KEYWORD: {keyword}",
        f"TITLE: {title}",
        f"INTENT: {intent_type}",
    ]
    if scope_statement:
        parts.append(f"SCOPE_STATEMENT: {scope_statement}")

    # ICP / audience context — primary driver of Agree style selection and
    # grounding. Pulled from the distilled brand voice card, which encodes
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
                f"pain points (anchor the Agree here): "
                f"{', '.join(brand_voice_card.audience_pain_points[:3])}"
            )
        if brand_voice_card.audience_goals:
            audience_parts.append(
                f"goals (the Promise should advance one of these): "
                f"{', '.join(brand_voice_card.audience_goals[:3])}"
            )
        if audience_parts:
            parts.append("\nAUDIENCE:")
            parts.extend(f"  {p}" for p in audience_parts)

    # Supporting data — enables data_led / research_reframe styles.
    if supporting_data:
        parts.append(f"\nSUPPORTING_DATA: {supporting_data}")

    # Article topic context — helps the LLM understand the article's scope
    # when crafting the curiosity-hook Preview. Not to be enumerated.
    if h2_list:
        parts.append("\nARTICLE_TOPICS (context only — do NOT enumerate these in the Preview):")
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
                f"DISCOURAGED (avoid where possible — softer than forbidden): "
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


def _validate_intro_blocks(
    agree: str, promise: str, preview: str
) -> tuple[bool, Optional[str]]:
    """Return (ok, retry_directive). retry_directive is the correction to
    feed into the retry prompt when ok is False."""
    if not agree.strip():
        return False, "Previous attempt: 'agree' block was empty. Write it now."
    if not promise.strip():
        return False, "Previous attempt: 'promise' block was empty. Write it now."
    if not preview.strip():
        return False, "Previous attempt: 'preview' block was empty. Write it now."

    for label, block in [("agree", agree), ("promise", promise), ("preview", preview)]:
        wc = _word_count(block)
        if wc > INTRO_MAX_WORDS_PER_BLOCK:
            return (
                False,
                f"Previous attempt: '{label}' block was {wc} words (max "
                f"{INTRO_MAX_WORDS_PER_BLOCK}). Shorten it.",
            )

    total = _word_count(agree) + _word_count(promise) + _word_count(preview)
    if total < INTRO_MIN_WORDS:
        return (
            False,
            f"Previous attempt was {total} words total, too short. Expand to "
            f"{INTRO_MIN_WORDS}–{INTRO_MAX_WORDS} words.",
        )
    if total > INTRO_MAX_WORDS:
        return (
            False,
            f"Previous attempt was {total} words total, too long. Trim to "
            f"{INTRO_MIN_WORDS}–{INTRO_MAX_WORDS} words.",
        )

    combined = f"{agree}\n{promise}\n{preview}"
    if _HEADING_MARKER_RE.search(combined):
        return False, "Previous attempt contained heading markers (#). Remove all # markers."
    if _LIST_MARKER_RE.search(combined):
        return (
            False,
            "Previous attempt contained list markers. Write prose only — no "
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
) -> ArticleSection:
    """One LLM call + at most one validation retry. Banned-term hits get
    their own retry per Section 4.4.3. Validation failures after the retry
    degrade to an accept-with-warning rather than aborting the run."""
    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []

    retry_directive: Optional[str] = None
    last_blocks: Optional[tuple[str, str, str]] = None

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

        agree = (result.get("agree") or "").strip()
        promise = (result.get("promise") or "").strip()
        preview = (result.get("preview") or "").strip()
        agree_style = (result.get("agree_style_selected") or "").strip()

        if not (agree and promise and preview):
            if attempt == 0:
                retry_directive = (
                    "Previous attempt was missing one or more required fields "
                    "(agree, promise, preview). Return all three."
                )
                continue
            return _placeholder_intro(intro_order)

        last_blocks = (agree, promise, preview)
        body = f"{agree}\n\n{promise}\n\n{preview}"

        # Banned-term check — same retry-then-abort policy as body sections
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

        ok, validation_directive = _validate_intro_blocks(agree, promise, preview)
        if ok:
            logger.info(
                "writer.intro.complete",
                extra={"agree_style": agree_style, "word_count": _word_count(body)},
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

    if last_blocks:
        agree, promise, preview = last_blocks
        body = f"{agree}\n\n{promise}\n\n{preview}"
        return ArticleSection(
            order=intro_order,
            level="none",
            type="intro",
            heading=None,
            body=body,
            word_count=_word_count(body),
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
