"""End-of-run format QA - "is this the right KIND of article?"

Every other writer validator checks the article's conformance to the
brief (word floors, citation coverage, format directives, structure
order). None of them can catch a brief that planned the wrong archetype
in the first place - the failure mode where "10 Best Freight Audit
Companies 2026" generated as informational prose and passed every check
because it conformed perfectly to a wrong plan.

This module closes that gap with one cheap Haiku call after final
assembly: given the keyword, the planned intent, and the final H2
outline, does the article's structure match the archetype a searcher
would expect? The verdict is warn-and-accept - a mismatch flags writer
metadata (surfaced on the run-detail QA panel), never aborts the run.
Best-effort: any API error or malformed response returns None (unknown),
which is the honest answer - flagging a failure as a mismatch would
mislead editors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import settings
from models.writer import ArticleSection

from modules.brief.llm import claude_json

logger = logging.getLogger(__name__)


# Mirrors the brief's intent taxonomy (models.brief.IntentType).
_VALID_ARCHETYPES = frozenset({
    "informational",
    "listicle",
    "how-to",
    "comparison",
    "ecom",
    "local-seo",
    "news",
    "informational-commercial",
})

_SYSTEM = (
    "You are a QA checker for SEO articles. Given a target keyword, the "
    "article archetype the pipeline planned, and the article's final H2 "
    "outline, judge whether the structure matches what a searcher of that "
    "keyword expects.\n\n"
    "Archetypes: informational, listicle, how-to, comparison, ecom, "
    "local-seo, news, informational-commercial.\n\n"
    'Respond with a single JSON object: {"matches": <bool>, '
    '"expected_archetype": "<archetype>", "note": "<one sentence>"}.\n'
    "- matches=true when the outline reads as the archetype the keyword "
    "calls for (a listicle keyword with ranked/parallel item H2s, a how-to "
    "keyword with sequential step H2s, etc.).\n"
    "- matches=false when the keyword clearly calls for a different "
    "archetype than the outline delivers.\n"
    "- expected_archetype is the archetype the KEYWORD calls for.\n"
    "- note briefly explains the verdict for a human editor."
)


@dataclass
class FormatQAResult:
    matches_intent: Optional[bool]
    expected_archetype: Optional[str]
    note: Optional[str]


_UNKNOWN = FormatQAResult(None, None, None)


def _content_h2_outline(article: list[ArticleSection]) -> list[str]:
    return [
        (s.heading or "").strip()
        for s in article
        if s.level == "H2" and s.type == "content" and (s.heading or "").strip()
    ]


async def check_format_qa(
    *,
    keyword: str,
    intent_type: str,
    title: str,
    article: list[ArticleSection],
) -> FormatQAResult:
    """One Haiku call judging keyword vs delivered structure. Never raises."""
    if not settings.writer_format_qa_enabled:
        return _UNKNOWN
    outline = _content_h2_outline(article)
    if not outline:
        return _UNKNOWN

    user = (
        f"Keyword: {keyword}\n"
        f"Planned archetype: {intent_type}\n"
        f"Article title: {title}\n"
        "Final H2 outline:\n"
        + "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(outline))
        + "\n\nDoes this structure match what a searcher of the keyword expects?"
    )
    try:
        result = await claude_json(
            _SYSTEM,
            user,
            max_tokens=200,
            temperature=0,
            model=settings.writer_format_qa_model,
        )
        if not isinstance(result, dict):
            return _UNKNOWN
        matches = result.get("matches")
        if not isinstance(matches, bool):
            return _UNKNOWN
        expected = result.get("expected_archetype")
        if expected not in _VALID_ARCHETYPES:
            expected = None
        note = (result.get("note") or "").strip() or None
        if not matches:
            logger.warning(
                "writer.format_qa.mismatch",
                extra={
                    "keyword": keyword,
                    "planned_intent": intent_type,
                    "expected_archetype": expected,
                    "note": note,
                },
            )
        return FormatQAResult(matches, expected, note)
    except Exception as exc:
        logger.warning("writer.format_qa.failed: %s", exc)
        return _UNKNOWN
