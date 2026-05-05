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
# title / h1 / h2 / h3 / paragraphs only). Derive FAQ-zone category
# targets from the paragraphs-zone aggregate (sie.zone_category_targets
# ["paragraphs"]) by the typical FAQ-to-paragraphs word budget ratio
# (~150 FAQ words across 3-5 answers vs ~1500 main-body paragraph
# words).
_FAQ_TO_PARAGRAPHS_BUDGET_RATIO = 0.12


def _scale_paragraphs_target(target: int) -> int:
    """Scale a paragraphs-zone target into a FAQ-zone target with a
    floor of 1 when the source is non-zero (FAQs always benefit from at
    least one mention of a category if paragraphs needs coverage)."""
    if target <= 0:
        return 0
    scaled = int(round(target * _FAQ_TO_PARAGRAPHS_BUDGET_RATIO))
    return max(scaled, 1)


def _derive_faq_category_targets(
    paragraphs_aggregate: dict[str, int],
) -> dict[str, int]:
    """Translate the paragraphs zone's category aggregate into a
    FAQ-zone equivalent. Returns the same three-key shape as the
    source: {entities, related_keywords, keyword_variants}.

    `paragraphs_aggregate` is a dict like
    `{"entities": 20, "related_keywords": 14, "keyword_variants": 6}`
    drawn from `sie.zone_category_targets["paragraphs"]`.
    """
    return {
        cat: _scale_paragraphs_target(int(paragraphs_aggregate.get(cat, 0) or 0))
        for cat in ("entities", "related_keywords", "keyword_variants")
    }


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
    paragraphs_zone_targets: Optional[dict[str, int]] = None,
) -> list[ArticleSection]:
    """Returns ArticleSection list: FAQ header H2 + per-question H3.

    SIE v1.4 — `paragraphs_zone_targets` is the body-zone three-bucket
    aggregate (`sie.zone_category_targets["paragraphs"]`). Internally
    scaled to FAQ-appropriate values via the FAQ_TO_PARAGRAPHS_BUDGET
    ratio.
    """
    if not faq_questions:
        return []

    if question_orders is None:
        question_orders = list(range(faq_header_order + 1, faq_header_order + 1 + len(faq_questions)))

    forbidden_terms = (brand_voice_card.banned_terms if brand_voice_card else []) or []
    excluded = [e["term"] for e in filtered_terms.excluded if e.get("term")]
    avoid = filtered_terms.avoid
    forbidden_combined = sorted(set(t.lower() for t in forbidden_terms + excluded + avoid if t))

    # SIE v1.4 — bucket required terms into three categories and surface
    # each separately to the FAQ prompt. Caps per category keep the
    # prompt small (FAQs are short — 3-5 answers × 40-80 words).
    entities_top: list[str] = []
    related_top: list[str] = []
    variants_top: list[str] = []
    for t in filtered_terms.required:
        if getattr(t, "is_entity", False):
            entities_top.append(t.term)
        elif getattr(t, "is_seed_fragment", False):
            variants_top.append(t.term)
        else:
            related_top.append(t.term)
    entities_top = entities_top[:6]
    related_top = related_top[:6]
    variants_top = variants_top[:4]

    faq_targets = _derive_faq_category_targets(paragraphs_zone_targets or {})

    user_parts = [
        f"KEYWORD: {keyword}",
        "\nFAQ_QUESTIONS:",
        *(f"  - {q}" for q in faq_questions),
    ]

    if brand_voice_card:
        if brand_voice_card.tone_adjectives:
            user_parts.append(
                f"\nTONE (every answer should read as): "
                f"{', '.join(brand_voice_card.tone_adjectives)}"
            )
        if brand_voice_card.voice_directives:
            user_parts.append(
                f"VOICE_DIRECTIVES (apply throughout): "
                f"{' | '.join(brand_voice_card.voice_directives[:3])}"
            )
        if brand_voice_card.preferred_terms:
            user_parts.append(
                f"FAVORED_PHRASING (use naturally where they fit): "
                f"{', '.join(brand_voice_card.preferred_terms[:15])}"
            )
        if brand_voice_card.discouraged_terms:
            user_parts.append(
                f"DISCOURAGED (avoid where possible — softer than forbidden): "
                f"{', '.join(brand_voice_card.discouraged_terms[:10])}"
            )
        if brand_voice_card.audience_summary:
            user_parts.append(f"\nAUDIENCE: {brand_voice_card.audience_summary}")
        if brand_voice_card.audience_pain_points:
            user_parts.append(f"PAIN_POINTS: {', '.join(brand_voice_card.audience_pain_points[:3])}")
        if brand_voice_card.audience_goals:
            user_parts.append(f"GOALS: {', '.join(brand_voice_card.audience_goals[:3])}")

    if entities_top:
        user_parts.append(f"\nENTITIES: {', '.join(entities_top)}")
    if related_top:
        user_parts.append(f"RELATED_KEYWORDS: {', '.join(related_top)}")
    if variants_top:
        user_parts.append(f"KEYWORD_VARIANTS: {', '.join(variants_top)}")

    coverage_directives = []

    def _add_directive(name: str, target: int, listed: int):
        if target <= 0 or listed <= 0:
            return
        eff = min(target, listed)
        plural = name if eff != 1 else name.rstrip("s") or name
        coverage_directives.append(
            f"  - at least {eff} distinct {plural} across the FAQ set"
        )

    _add_directive("entities", faq_targets["entities"], len(entities_top))
    _add_directive("related keywords", faq_targets["related_keywords"], len(related_top))
    _add_directive("keyword variants", faq_targets["keyword_variants"], len(variants_top))

    if coverage_directives:
        user_parts.append(
            "\nCOVERAGE_TARGETS (distribute naturally; not every answer "
            "needs one of each):\n" + "\n".join(coverage_directives)
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
