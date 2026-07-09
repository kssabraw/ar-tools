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


# ---------------------------------------------------------------------------
# Notes-landed judge - did the article honor the user's writer notes?
# ---------------------------------------------------------------------------

_NOTES_SYSTEM = (
    "You are a QA checker verifying that an article honored the account "
    "team's editorial notes. Split the notes into distinct directives (a "
    "single note may contain several). For each directive judge whether the "
    "article satisfies it. Tolerate paraphrase and abbreviation - a "
    "directive to mention 'Zero Down Supply Chain Services' is satisfied by "
    "'ZDSCS' or a clear paraphrase of the company.\n\n"
    'Respond with a single JSON object: {"directives": [{"note": '
    '"<the directive, briefly restated>", "landed": <bool>, "evidence": '
    '"<short quote from the article when landed, else why not>"}]}.'
)

# Bound the article text sent to the judge. 30k chars comfortably covers a
# ~3000-word article with headings; anything longer is clipped from the end
# (notes overwhelmingly land in title/intro/body, not the FAQ tail).
_NOTES_ARTICLE_CLIP = 30_000


@dataclass
class NotesLandedResult:
    # One entry per directive: {"note": str, "landed": bool, "evidence": str}
    verdicts: list[dict]
    # AND across directives. None = no notes, check disabled, or judge failed
    # (unknown - the honest answer, same convention as the ICP callout judge).
    landed_all: Optional[bool]


_NOTES_UNKNOWN = NotesLandedResult([], None)


def _article_text(article: list[ArticleSection]) -> str:
    parts: list[str] = []
    for s in article:
        if s.heading:
            parts.append(s.heading)
        if s.body:
            parts.append(s.body)
    return "\n\n".join(parts)[:_NOTES_ARTICLE_CLIP]


async def check_notes_landed(
    *,
    user_notes: Optional[str],
    article: list[ArticleSection],
) -> NotesLandedResult:
    """One Haiku call judging whether the final article honored the user's
    per-run writer notes. Skipped when there are no notes. Never raises."""
    notes = (user_notes or "").strip()
    if not notes or not settings.writer_notes_qa_enabled:
        return _NOTES_UNKNOWN
    text = _article_text(article)
    if not text:
        return _NOTES_UNKNOWN

    user = (
        f"EDITORIAL NOTES:\n{notes}\n\n"
        f"ARTICLE:\n{text}\n\n"
        "Judge each directive now."
    )
    try:
        result = await claude_json(
            _NOTES_SYSTEM,
            user,
            max_tokens=600,
            temperature=0,
            model=settings.writer_format_qa_model,
        )
        raw = result.get("directives") if isinstance(result, dict) else None
        if not isinstance(raw, list) or not raw:
            return _NOTES_UNKNOWN
        verdicts: list[dict] = []
        for d in raw:
            if not isinstance(d, dict) or not isinstance(d.get("landed"), bool):
                continue
            verdicts.append({
                "note": str(d.get("note") or "").strip()[:300],
                "landed": d["landed"],
                "evidence": str(d.get("evidence") or "").strip()[:300],
            })
        if not verdicts:
            return _NOTES_UNKNOWN
        landed_all = all(v["landed"] for v in verdicts)
        if not landed_all:
            logger.warning(
                "writer.notes_qa.not_landed",
                extra={
                    "missed": [v["note"] for v in verdicts if not v["landed"]][:5],
                },
            )
        return NotesLandedResult(verdicts, landed_all)
    except Exception as exc:
        logger.warning("writer.notes_qa.failed: %s", exc)
        return _NOTES_UNKNOWN


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
