"""Deterministic brand-guide checks beyond banned terms.

`banned_terms.py` already hard-enforces the guide's prohibitions. This module
adds the two checks that were missing, both of which a real client audit
surfaced on shipped articles:

  * **grammatical person** — a guide that says "write as we/our" lost to the
    generator's own default preference for third person, and nothing noticed.
  * **required phrasing** — the guide's preferred terms reached the prompt as a
    suggestion and were simply not used.

Both are warnings, never aborts. Banned terms in a heading remain the only
hard stop (see `banned_terms.BannedTermLeakage`): a missing preferred term is
an editorial note, not a reason to throw away a finished article.

Shared by the blog Writer and the Service/Location Writer, which already share
the distillation and banned-term layer. Thresholds are deliberately identical
to `nlp-api/voice_card.py` so a page and an article are judged the same way —
if you change one, change both.
"""

from __future__ import annotations

import re
from typing import Optional

from models.writer import BrandVoiceCard

from .banned_terms import build_banned_regex

_FIRST_PERSON_RE = re.compile(r"\b(?:we|we're|we've|we'll|our|ours|us)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z']+")

# Per 1,000 words. Set wide so ordinary prose variation never trips them: a
# genuinely first-person article lands well above 6, a strictly third-person one
# near 0. A noisy warning gets ignored and stops being a check at all.
_FIRST_PERSON_ABSENT_MAX = 1.0
_THIRD_PERSON_EXCEEDED_MIN = 6.0
_MIN_WORDS_FOR_PERSON_CHECK = 100


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def check_person(text: str, person: str) -> Optional[dict]:
    """Flag prose whose grammatical person contradicts the brand guide.

    Returns None when the guide is silent (`person` empty), when the text is
    too short for density to mean anything, or when the article already matches.
    """
    if person not in ("first", "third"):
        return None
    words = _word_count(text)
    if words < _MIN_WORDS_FOR_PERSON_CHECK:
        return None

    hits = len(_FIRST_PERSON_RE.findall(text))
    density = (hits / words) * 1000
    detail = f"{hits} first-person words across {words} ({density:.1f}/1k)"

    if person == "first" and density <= _FIRST_PERSON_ABSENT_MAX:
        return {
            "check": "person",
            "severity": "warning",
            "detail": detail,
            "message": (
                "The brand guide specifies first person (we/our) but the article is "
                "written in third person."
            ),
        }
    if person == "third" and density >= _THIRD_PERSON_EXCEEDED_MIN:
        return {
            "check": "person",
            "severity": "warning",
            "detail": detail,
            "message": (
                "The brand guide specifies third person (name the brand) but the "
                "article leans on we/our."
            ),
        }
    return None


def check_preferred_terms(text: str, preferred_terms: list[str]) -> Optional[dict]:
    """Flag guide-preferred phrasings that never appear in the article."""
    missing: list[str] = []
    for term in preferred_terms or []:
        regex = build_banned_regex([term])  # word-boundary matcher, not a ban
        if regex is None or not regex.search(text or ""):
            missing.append(term)
    if not missing:
        return None
    return {
        "check": "preferred_terms",
        "severity": "warning",
        "terms": missing,
        "message": (
            "The brand guide names this phrasing as preferred and it never appears: "
            + ", ".join(f'"{t}"' for t in missing)
        ),
    }


def check_article(text: str, card: Optional[BrandVoiceCard]) -> list[dict]:
    """Run every deterministic check against an article's full text.

    `text` should be the rendered prose (title + headings + bodies). Returns an
    empty list when there is no card, no text, or nothing to report.
    """
    if card is None or not (text or "").strip():
        return []
    violations: list[dict] = []
    person = check_person(text, getattr(card, "person", "") or "")
    if person:
        violations.append(person)
    preferred = check_preferred_terms(text, list(card.preferred_terms or []))
    if preferred:
        violations.append(preferred)
    return violations


def article_text(title: str, sections: list) -> str:
    """Flatten a finished article into the text the checks read.

    Takes `ArticleSection`-shaped objects (or anything with `.heading`/`.body`)
    so it can serve both writers without importing either's pipeline.
    """
    parts: list[str] = [title or ""]
    for section in sections or []:
        heading = getattr(section, "heading", None) or ""
        body = getattr(section, "body", None) or ""
        if heading:
            parts.append(heading)
        if body:
            parts.append(body)
    return "\n".join(p for p in parts if p)
