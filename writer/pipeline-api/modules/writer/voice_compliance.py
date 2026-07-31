"""Deterministic brand-guide checks, as consumed by the Service/Location writer.

These used to carry their own copies of the person-density thresholds and the
required-term matcher. That was one implementation too many: the vendored
`voice_card.py` (byte-identical to nlp-api's, sync-guarded by a test) already
defines them, and two copies of a threshold in one service is a drift waiting to
happen — the page path and the article path would start disagreeing about what
"wrong grammatical person" means without anyone noticing.

So this is now an adapter, not an implementation. It keeps the granular
`check_person` / `check_preferred_terms` API the Service writer calls, and
delegates every actual decision to the shared module.

Both remain warnings, never aborts. Banned terms in a heading are still the only
hard stop (see `banned_terms.BannedTermLeakage`): a missing preferred term is an
editorial note, not a reason to throw away a finished page.
"""

from __future__ import annotations

from typing import Optional

from models.writer import BrandVoiceCard

from . import voice_card as vcard


def _findings(text: str, card: dict) -> dict[str, dict]:
    """Run the shared checks and index the results by check name."""
    return {v["check"]: v for v in vcard.check_voice_compliance(text or "", card)}


def check_person(text: str, person: str) -> Optional[dict]:
    """Flag prose whose grammatical person contradicts the brand guide.

    Returns None when the guide is silent, when the text is too short for
    density to mean anything, or when the prose already matches.
    """
    if person not in ("first", "third"):
        return None
    card = vcard.empty_card()
    card["person"] = person
    return _findings(text, card).get("person")


def check_preferred_terms(text: str, preferred_terms: list[str]) -> Optional[dict]:
    """Flag guide-preferred phrasings that never appear in the text."""
    if not preferred_terms:
        return None
    card = vcard.empty_card()
    card["must_use_terms"] = list(preferred_terms)
    finding = _findings(text, card).get("must_use_terms")
    if finding is None:
        return None
    # The Service writer's callers know these as "preferred terms"; the shared
    # module calls the same list must_use_terms. Rename on the way out so the
    # message and check name match the vocabulary of this side of the fence.
    finding = dict(finding)
    finding["check"] = "preferred_terms"
    finding["message"] = (
        "The brand guide names this phrasing as preferred and it never appears: "
        + ", ".join(f'"{t}"' for t in finding.get("terms", []))
    )
    return finding


def check_article(text: str, card: Optional[BrandVoiceCard]) -> list[dict]:
    """Every deterministic check against a finished piece of prose.

    `text` should be the rendered content (title + headings + bodies). Returns
    an empty list when there is no card, no text, or nothing to report.
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
    """Flatten finished content into the text the checks read.

    Takes `ArticleSection`-shaped objects (or anything with `.heading`/`.body`)
    so it can serve either writer without importing their pipelines.
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
