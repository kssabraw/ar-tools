"""Step 5 — FAQ writing.

One LLM call covering all FAQs at once. Each answer: 40-80 words,
self-contained, no cross-references to article sections, answer-first.

Per writer-module-v1_5-change-spec_2.md §4.2: inject brand voice (lighter
than section writing) + full audience picture.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.writer import ArticleSection, BrandVoiceCard

from modules.brief.llm import claude_json

from .banned_terms import BannedTermLeakage, find_banned
from .reconciliation import FilteredSIETerms

logger = logging.getLogger(__name__)


# FAQs aren't a SIE-tracked zone (the SIE pipeline computes
# title / h1 / h2 / h3 / paragraphs only). Derive a FAQ usage target
# from the paragraphs target by the typical FAQ-to-paragraphs word
# budget ratio (~150 FAQ words across 3-5 answers vs ~1500 main-body
# paragraph words). That gives us a reasonable per-question pacing
# floor without inventing a new SIE zone.
_FAQ_TO_PARAGRAPHS_BUDGET_RATIO = 0.12


def _derive_faq_zone_target(
    filtered_terms: FilteredSIETerms,
) -> tuple[int, int]:
    """Sum the paragraphs-zone target/max across required terms and scale
    by the FAQ-vs-paragraphs budget ratio. Returns (target, max) — the
    aggregate count of distinct required-term mentions the FAQ section
    should hit (target) and absolute ceiling (max). Both are 0 when SIE
    hasn't surfaced per-zone targets (legacy responses).
    """
    para_target = 0
    para_max = 0
    for term in filtered_terms.required:
        zones = getattr(term, "zones", {}) or {}
        if not isinstance(zones, dict):
            continue
        para = zones.get("paragraphs") or {}
        if not isinstance(para, dict):
            continue
        para_target += int(para.get("target", 0) or 0)
        para_max += int(para.get("max", 0) or 0)
    derived_target = int(round(para_target * _FAQ_TO_PARAGRAPHS_BUDGET_RATIO))
    derived_max = int(round(para_max * _FAQ_TO_PARAGRAPHS_BUDGET_RATIO))
    if para_target > 0 and derived_target == 0:
        derived_target = 1
    if derived_max < derived_target:
        derived_max = derived_target
    return (derived_target, derived_max)


FAQ_SYSTEM = """You write FAQ answers for a blog post.

OUTPUT FORMAT:
{"faqs": [{"question": "<exact question text>", "answer": "<answer prose>"}]}

WRITING RULES:
- Each answer is 40-80 words, prose only (no markdown headings or lists in answers).
- Answer-first: open with a direct response, then 1-2 supporting sentences.
- Self-contained: a reader must understand the answer without reading other parts of the article.
- Never use "as mentioned above" or any reference to other sections.
- Reflect ICP audience phrasing patterns; not generic SEO question templates.
- Do NOT use any FORBIDDEN_TERM anywhere in the answer.
- Use REQUIRED_TERMS naturally where they fit; do not force them.
- The seed keyword or its primary sub-phrase must appear in at least 2 answers across the FAQ set."""


async def write_faqs(
    keyword: str,
    faq_questions: list[str],
    filtered_terms: FilteredSIETerms,
    brand_voice_card: Optional[BrandVoiceCard],
    banned_regex,
    faq_header_text: str = "Frequently Asked Questions",
    faq_header_order: int = 0,
    question_orders: Optional[list[int]] = None,
) -> list[ArticleSection]:
    """Returns ArticleSection list: FAQ header H2 + per-question H3."""
    if not faq_questions:
        return []

    if question_orders is None:
        question_orders = list(range(faq_header_order + 1, faq_header_order + 1 + len(faq_questions)))

    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []
    excluded = [e["term"] for e in filtered_terms.excluded if e.get("term")]
    avoid = filtered_terms.avoid
    forbidden_combined = sorted(set(t.lower() for t in forbidden_terms + excluded + avoid if t))

    required_terms_str = ""
    if filtered_terms.required:
        top = filtered_terms.required[:8]
        required_terms_str = ", ".join(t.term for t in top)

    # PRD v2.6 wiring — FAQs aren't a SIE zone, derive from paragraphs.
    faq_target, faq_max = _derive_faq_zone_target(filtered_terms)

    user_parts = [
        f"KEYWORD: {keyword}",
        "\nFAQ_QUESTIONS:",
        *(f"  - {q}" for q in faq_questions),
    ]

    if brand_voice_card:
        if brand_voice_card.tone_adjectives:
            user_parts.append(f"\nTONE: {', '.join(brand_voice_card.tone_adjectives)}")
        if brand_voice_card.voice_directives:
            user_parts.append(f"VOICE_DIRECTIVES: {' | '.join(brand_voice_card.voice_directives[:3])}")
        if brand_voice_card.audience_summary:
            user_parts.append(f"\nAUDIENCE: {brand_voice_card.audience_summary}")
        if brand_voice_card.audience_pain_points:
            user_parts.append(f"PAIN_POINTS: {', '.join(brand_voice_card.audience_pain_points[:3])}")
        if brand_voice_card.audience_goals:
            user_parts.append(f"GOALS: {', '.join(brand_voice_card.audience_goals[:3])}")

    if required_terms_str:
        user_parts.append(f"\nREQUIRED_TERMS: {required_terms_str}")
        if faq_target > 0:
            user_parts.append(
                f"REQUIRED_TERM_USAGE_TARGET: aim for at least {faq_target} "
                f"distinct REQUIRED_TERM mentions across the FAQ set "
                f"(do not exceed {faq_max}). Distribute naturally; not "
                f"every answer needs one."
            )

    if forbidden_combined:
        user_parts.append(f"\nFORBIDDEN_TERMS: {', '.join(forbidden_combined[:50])}")

    user_parts.append("\nWrite the JSON object now. One entry per question, in input order.")
    user = "\n".join(user_parts)

    last_retry_term: Optional[str] = None
    for attempt in range(2):
        sys_prompt = FAQ_SYSTEM
        if last_retry_term:
            sys_prompt += f"\n\nIMPORTANT: A previous attempt included the forbidden term '{last_retry_term}'. Rewrite without it."
        try:
            result = await claude_json(sys_prompt, user, max_tokens=2500, temperature=0.4)
        except Exception as exc:
            logger.warning("FAQ writing failed: %s", exc)
            return _placeholder_faqs(faq_questions, faq_header_text, faq_header_order, question_orders)

        if not isinstance(result, dict):
            return _placeholder_faqs(faq_questions, faq_header_text, faq_header_order, question_orders)

        faqs_raw = result.get("faqs") or []
        if not isinstance(faqs_raw, list) or not faqs_raw:
            return _placeholder_faqs(faq_questions, faq_header_text, faq_header_order, question_orders)

        # Banned-term check across all answers
        body_match: Optional[str] = None
        for entry in faqs_raw:
            if not isinstance(entry, dict):
                continue
            answer = entry.get("answer", "")
            matches = find_banned(answer, banned_regex)
            if matches:
                body_match = matches[0]
                break

        if body_match and attempt == 0:
            last_retry_term = body_match
            continue
        if body_match and attempt == 1:
            raise BannedTermLeakage(
                term=body_match,
                location="FAQ answer (after retry)",
                snippet="",
            )

        return _build_faq_sections(faqs_raw, faq_questions, faq_header_text, faq_header_order, question_orders)

    return _placeholder_faqs(faq_questions, faq_header_text, faq_header_order, question_orders)


def _build_faq_sections(
    raw: list[dict],
    questions: list[str],
    header_text: str,
    header_order: int,
    question_orders: list[int],
) -> list[ArticleSection]:
    """Map LLM output back to questions; preserve question order."""
    by_question = {entry.get("question", "").strip().lower(): entry for entry in raw if isinstance(entry, dict)}
    sections: list[ArticleSection] = [ArticleSection(
        order=header_order,
        level="H2",
        type="faq-header",
        heading=header_text,
        body="",
    )]
    for q, q_order in zip(questions, question_orders):
        match = by_question.get(q.strip().lower())
        answer = (match.get("answer", "") if match else "").strip()
        sections.append(ArticleSection(
            order=q_order,
            level="H3",
            type="faq-question",
            heading=q,
            body=answer,
            word_count=len(answer.split()),
        ))
    return sections


def _placeholder_faqs(
    questions: list[str],
    header_text: str,
    header_order: int,
    question_orders: list[int],
) -> list[ArticleSection]:
    sections = [ArticleSection(
        order=header_order, level="H2", type="faq-header",
        heading=header_text, body="",
    )]
    for q, q_order in zip(questions, question_orders):
        sections.append(ArticleSection(
            order=q_order, level="H3", type="faq-question",
            heading=q,
            body="[FAQ GENERATION FAILED — MANUAL REVIEW REQUIRED]",
        ))
    return sections
