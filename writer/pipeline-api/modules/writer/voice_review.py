"""Post-write brand-voice review for the Blog and Service/Location writers.

The nlp-api page generators have scored voice across eight dimensions and
rewritten off-voice pages since 2026-07-31. Articles had only the two
mechanical checks — banned terms and grammatical person — so an article could
be written entirely off-voice, address none of the ICP's stated worries, and
ship with nothing flagged beyond "a preferred term is missing".

This closes that. Same scorecard, same weights, same pass bar as the page path,
because "did it sound like the client" must not mean two different things
depending on which generator produced the text. The scoring core is the
vendored `voice_card.py` (byte-identical to nlp-api's; a unit test enforces it),
so the dimensions and their weights are defined exactly once for the suite.

Two LLM calls, both best-effort and both skipped entirely when the article
already passes:

  1. `score_article_voice` — judges the assembled article against the card,
     returning the eight dimensions with a verbatim quote each.
  2. `revise_article_voice` — rewrites ONLY the failing sections, keyed by
     heading, and returns replacement bodies.

The revision is deliberately body-only. Headings carry the SEO structure the
brief and the heading optimizer produced — entity placement, question format,
keyword variants — and a voice pass has no business touching them. Rewriting
prose inside a fixed skeleton is exactly the split the page path already
enforces ("structure is SEO's, expression is the client's").

Never raises: a scoring or revision failure leaves the article as written and
returns the deterministic verdict, which needs no network at all.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from models.writer import ArticleSection, BrandVoiceCard

from . import voice_card as vcard

logger = logging.getLogger(__name__)

JudgeFn = Callable[..., Awaitable[Any]]

# Whole-article text sent to the judge. Long enough for a 2,500-word article
# plus headings; head+tail truncated beyond that so tone drift in the closing
# sections is still visible (the failure mode is "opens in voice, drifts by the
# third heading", which head-only truncation would hide).
_SCORE_HEAD_CHARS = 9000
_SCORE_TAIL_CHARS = 5000

# A revision pass rewrites at most this many sections. Beyond it the article is
# wrong at the brief level, not the sentence level, and rewriting everything
# would be a re-generation wearing a revision's clothes.
_MAX_REVISED_SECTIONS = 6

# Match the nlp page path (MAX_VOICE_CORRECTION_PASSES): up to three revision
# passes toward the voice bar, keeping the best-scoring one — a section revision
# can score lower than the version before it, so keep-latest would ship the
# regression.
MAX_VOICE_REVISION_PASSES = 3


def card_to_dict(card: Optional[BrandVoiceCard]) -> dict:
    """Map the writer's `BrandVoiceCard` onto the suite-wide card shape.

    The two evolved separately: the writer calls them `preferred_terms` and
    `banned_terms`, the shared card calls the same things `must_use_terms` and
    `never_use_terms`. Mapping here (rather than renaming the writer's model)
    keeps every existing consumer of `BrandVoiceCard` untouched.

    `audience_label` is synthesised from the personas/verticals the writer's
    distillation captures but the shared card has no field for, so the
    `audience_fit` dimension has something concrete to judge against.
    """
    if card is None:
        return vcard.empty_card()

    label = card.audience_summary or ""
    if card.audience_personas or card.audience_verticals:
        parts = [", ".join(card.audience_personas[:3])] if card.audience_personas else []
        if card.audience_verticals:
            parts.append("in " + ", ".join(card.audience_verticals[:3]))
        joined = " ".join(p for p in parts if p).strip()
        label = joined or label

    return vcard.parse_voice_card({
        "brand_name": card.brand_name,
        "tone_adjectives": list(card.tone_adjectives or []),
        "person": card.person,
        "voice_directives": list(card.voice_directives or []),
        "sentence_rhythm": card.sentence_rhythm,
        "must_use_terms": list(card.preferred_terms or []),
        "never_use_terms": list(card.banned_terms or []),
        "discouraged_terms": list(card.discouraged_terms or []),
        "differentiators": list(card.differentiators or []),
        "signature_phrases": list(card.signature_phrases or []),
        "cta_language": list(card.cta_language or []),
        "audience_label": label,
        "audience_summary": card.audience_summary,
        "audience_pain_points": list(card.audience_pain_points or []),
        "audience_triggers": list(card.audience_triggers or []),
        "audience_motivations": list(card.audience_motivations or []),
        "audience_objections": list(card.audience_objections or []),
    })


def article_text(title: str, sections: list) -> str:
    """Flatten a finished article into the text the review reads."""
    parts: list[str] = [title or ""]
    for section in sections or []:
        heading = getattr(section, "heading", None) or ""
        body = getattr(section, "body", None) or ""
        if heading:
            parts.append(heading)
        if body:
            parts.append(body)
    return "\n\n".join(p for p in parts if p)


def _truncate(text: str) -> str:
    """Head + tail. The characteristic failure is an article that opens in the
    brand's register and drifts into generic copy by the end, which head-only
    truncation would hide from the judge."""
    if len(text) <= _SCORE_HEAD_CHARS + _SCORE_TAIL_CHARS:
        return text
    return (
        text[:_SCORE_HEAD_CHARS]
        + "\n\n…[middle truncated]…\n\n"
        + text[-_SCORE_TAIL_CHARS:]
    )


_SCORE_SYSTEM = """You are an adversarial brand-voice auditor. Your job is to find where an ARTICLE DRIFTS off a client's written brand guide and stops speaking to their ideal customer — not to confirm that it reads well. "Reads professionally" is not the standard: an article that could be published on any competitor's site is a FAILING article here.

Score EIGHT dimensions, each 0-100, each with a short verbatim quote FROM THE ARTICLE as evidence.

── SCORING DISCIPLINE (read before scoring any dimension) ──
Score each dimension against these bands, and when the evidence is mixed, choose the LOWER band:

  90-100  Unmistakably THIS client. Could not be confused for a competitor. The guide's tone, style and vocabulary are present in EVERY section, not just the intro. Rare — it must be earned.
  75-89   On-brand with lapses. Clearly following the guide, but drifts in places: a section or two go generic, a required phrasing is missing, or the voice thins toward the end.
  60-74   Competent but ANONYMOUS. Well-written and error-free, yet it reads like generic quality copy with the client's name dropped in. This is the DEFAULT for an article that "reads fine" but is not distinctly this client. Most articles that feel off-brand belong here.
  40-59   Off-brand. Actively contradicts the guide's tone, person or vocabulary, or is written to a generic reader the ICP does not describe.
  0-39    No discernible relationship to the guide or the ICP.

HARD RULES:
- Never award 75+ for the mere absence of errors. A score of 75 or higher requires POSITIVE evidence of this client's specific voice — name it.
- Score the WHOLE article. A strong intro does not rescue a generic body; if the voice fades after the first section, the dimension is mid-band at best.
- `evidence` must quote the WEAKEST passage you can find for that dimension — the place it drifts — not the best line. Score to that passage. Only if you genuinely cannot find a weak passage do you quote the strongest and justify a high score.
- For any dimension you score 85 or above, the `issues`/`recommendations` must state explicitly what is distinctly this client's about it. If you cannot, the score is too high.

Judge each dimension by asking what LOW looks like:

  tone            — Take the FLATTEST section of the article. Does it still carry the guide's stated tone adjectives, or has it settled into neutral copy? Opening in the brand's register and flattening by the third heading is a mid-band score, not a high one.
  writing_style   — Sentence rhythm, length variation, formality and jargon level versus the guide. LOW = uniform cadence and generic phrasing the guide's own author would not recognise as theirs.
  person          — Grammatical person matches what the guide specifies (first person "we/our" vs naming the brand). Any drift to the wrong person, even intermittently, is LOW.
  vocabulary      — Required phrasing present; forbidden and discouraged terms absent. LOW = missing the guide's words, or leaning on filler and boilerplate superlatives ("top-notch", "unparalleled", "state-of-the-art", "your trusted partner") that any brand could use.
  audience_fit    — Remove the audience's name from the article. Is there anything left that proves the writer knew WHO they were writing to — their situation, what brought them here? If not, it is a generic reader with a label pasted on: LOW.
  pain_points     — Count how many of the specific worries, hesitations and objections the ICP names the article actually engages. Merely asserting that the topic matters, without naming what the reader fears, is LOW.
  cta_fit         — Does the closing ask use the client's own CTA language and match the reader's readiness to act? A generic "contact us today" in place of the client's CTA is LOW.
  distinctiveness — Could this article be published on a competitor's site by swapping the brand name? Assume it could until the article proves otherwise. If it could, score LOW and say so. This is the single most important dimension here.

APPLICABILITY: if the guide and ICP genuinely say nothing about a dimension (e.g. no sentence-rhythm guidance at all), return `"applicable": false` for it rather than inventing a standard. It is excluded from the score instead of dragging it down. Do NOT mark a dimension inapplicable to dodge a low score.

Judge EXPRESSION and AUDIENCE only. Do NOT penalise the article for its heading structure, section order, FAQ count, citations, key-takeaways block or word count — those are editorial requirements scored elsewhere.

Return ONLY this JSON object:
{
  "tone":            {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "writing_style":   {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "person":          {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "vocabulary":      {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "audience_fit":    {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "pain_points":     {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "cta_fit":         {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []},
  "distinctiveness": {"score": 0, "applicable": true, "evidence": "", "issues": [], "recommendations": []}
}"""


def build_score_prompt(text: str, card: dict) -> str:
    """User prompt for the scoring call. Pure, so a test can assert the guide
    actually reaches the judge."""
    return (
        vcard.render_voice_card_block(card)
        + "\n\n=== ARTICLE ===\n"
        + _truncate(text)
        + "\n\nScore the eight dimensions now."
    )


async def score_article_voice(
    text: str, card: dict, judge_fn: Optional[JudgeFn] = None
) -> dict:
    """The eight scored dimensions, or `{}` when the call fails.

    `{}` is honest and handled: the scorecard marks itself
    `analysis="deterministic_only"` and the regex findings still stand.
    """
    if vcard.is_card_empty(card) or not (text or "").strip():
        return {}
    fn = judge_fn or _default_judge
    try:
        result = await fn(_SCORE_SYSTEM, build_score_prompt(text, card),
                          max_tokens=2500, temperature=0)
    except Exception as exc:
        logger.warning(
            "writer.voice_review.score_failed",
            extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
        )
        return {}
    return result if isinstance(result, dict) else {}


_REVISE_SYSTEM = """You are revising an article's PROSE so it follows the client's brand guide. You are not rewriting the article.

HARD RULES:
- Change ONLY the wording. Keep every factual claim, statistic, citation marker, name, number and link exactly as it is.
- Do NOT change, reorder, add or remove headings. You are given specific sections by heading; return replacement BODY text for those headings only.
- Keep each section's approximate length and its structure — if the body has a bulleted list, the replacement has the same list with the same items, reworded.
- Keep the opening sentence of each section a direct, self-contained claim that names its subject. Rewriting for voice is not a licence for vague openers or pronouns that only resolve from an earlier sentence.
- Never introduce a term the guide forbids.

Return ONLY this JSON object, with one entry per section you were asked to revise:
{"sections": [{"heading": "<the heading exactly as given>", "body": "<the revised body>"}]}"""


def build_revise_prompt(
    card: dict, scorecard: dict, sections: list[tuple[str, str]]
) -> str:
    """User prompt for the revision call: the guide, what's wrong, and the
    sections to fix. Pure."""
    parts = [vcard.render_voice_card_block(card), ""]
    corrections = "\n\n".join(part for part in (
        vcard.violations_to_corrections(scorecard.get("violations")),
        vcard.voice_deficiency_text(scorecard.get("deficiencies")),
    ) if part)
    if corrections:
        parts += [corrections, ""]
    parts.append("=== SECTIONS TO REVISE ===")
    for heading, body in sections:
        parts.append(f"\n--- HEADING: {heading}\n{body}")
    parts.append("\nReturn the JSON object with the revised bodies now.")
    return "\n".join(parts)


def select_sections_to_revise(
    article: list, scorecard: dict, card: dict
) -> list[tuple[str, str]]:
    """Which sections a revision pass should rewrite, worst offenders first.

    A section is selected when it contains a forbidden term (a fact — those must
    be rewritten wherever they appear) and otherwise by length, on the reasoning
    that a whole-article tone failure is carried mostly by the longest prose.
    Capped, because rewriting every section is a re-generation, not a revision.
    """
    if not scorecard.get("needs_rewrite"):
        return []
    candidates: list[tuple[int, str, str]] = []
    never_regex = vcard.build_term_regex((card or {}).get("never_use_terms") or [])
    for section in article or []:
        heading = getattr(section, "heading", None) or ""
        body = getattr(section, "body", None) or ""
        if not heading or not body.strip():
            continue
        # Priority 0 = contains a forbidden term, 1 = everything else.
        offends = bool(never_regex and never_regex.search(f"{heading}\n{body}"))
        candidates.append((0 if offends else 1, heading, body))

    if not candidates:
        return []
    # Forbidden-term sections first; within each tier, longest prose first.
    candidates.sort(key=lambda c: (c[0], -len(c[2])))
    return [(heading, body) for _, heading, body in candidates[:_MAX_REVISED_SECTIONS]]


def apply_revisions(article: list, revisions: Any) -> int:
    """Replace section bodies in place from a revision response.

    Returns how many sections were actually changed. Tolerant by design: an
    unrecognised heading, a blank body, or a malformed payload is skipped
    rather than corrupting the article — a partial revision is strictly better
    than a lost one.
    """
    if not isinstance(revisions, dict):
        return 0
    entries = revisions.get("sections")
    if not isinstance(entries, list):
        return 0

    by_heading = {
        (getattr(s, "heading", None) or "").strip().lower(): s
        for s in (article or [])
        if getattr(s, "heading", None)
    }
    applied = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        heading = str(entry.get("heading") or "").strip().lower()
        body = entry.get("body")
        if not heading or not isinstance(body, str) or not body.strip():
            continue
        section = by_heading.get(heading)
        if section is None:
            logger.info(
                "writer.voice_review.unknown_heading",
                extra={"heading": heading[:120]},
            )
            continue
        section.body = body.strip()
        if hasattr(section, "word_count"):
            section.word_count = len(body.split())
        applied += 1
    return applied


def _rank_key(scorecard: Optional[dict]) -> tuple:
    """Keep-best ranking: fewest critical violations first, then highest voice
    score. A higher tuple = a better article to ship. `None`/unscored ranks below
    any real score. Mirrors nlp-api `main._voice_rank_key`."""
    sc = scorecard or {}
    crit = sc.get("critical_count") or 0
    score = sc.get("score")
    score = score if isinstance(score, (int, float)) and not isinstance(score, bool) else float("-inf")
    return (-crit, score)


async def review_article_voice(
    title: str,
    article: list[ArticleSection],
    brand_card: Optional[BrandVoiceCard],
    *,
    judge_fn: Optional[JudgeFn] = None,
    max_passes: int = MAX_VOICE_REVISION_PASSES,
) -> Optional[dict]:
    """Score the finished article against the guide and revise it if it falls
    short. Mutates `article` in place. Returns the scorecard, or None when the
    client has no guide (nothing to check against).

    Never raises. A failure at any step leaves the article exactly as written
    and still returns the deterministic verdict.
    """
    card = card_to_dict(brand_card)
    if vcard.is_card_empty(card):
        return None

    def _measure() -> tuple[str, list[dict]]:
        text = article_text(title, article)
        violations = vcard.check_voice_compliance(text, card)
        return text, violations

    text, violations = _measure()
    dimensions = await score_article_voice(text, card, judge_fn)
    scorecard = vcard.voice_scorecard(dimensions, violations)

    # Keep-best: a section-level revision can score LOWER than the version before
    # it, so track the strongest article state (section bodies + its scorecard)
    # and restore it at the end rather than shipping whatever the last pass left.
    def _snapshot() -> list[str]:
        return [getattr(s, "body", "") or "" for s in article]

    def _restore(bodies: list[str]) -> None:
        for section, body in zip(article, bodies):
            section.body = body
            if hasattr(section, "word_count"):
                section.word_count = len(body.split())

    best_bodies = _snapshot()
    best_scorecard = scorecard

    for _pass in range(max(0, max_passes)):
        if not scorecard.get("needs_rewrite"):
            break
        targets = select_sections_to_revise(article, scorecard, card)
        if not targets:
            break
        fn = judge_fn or _default_judge
        try:
            revisions = await fn(
                _REVISE_SYSTEM,
                build_revise_prompt(card, scorecard, targets),
                max_tokens=8000,
                temperature=0.2,
            )
        except Exception as exc:
            logger.warning(
                "writer.voice_review.revise_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc)[:300]},
            )
            break
        if not apply_revisions(article, revisions):
            logger.warning("writer.voice_review.revision_applied_nothing")
            break

        text, violations = _measure()
        dimensions = await score_article_voice(text, card, judge_fn)
        scorecard = vcard.voice_scorecard(dimensions, violations)
        if _rank_key(scorecard) > _rank_key(best_scorecard):
            best_bodies = _snapshot()
            best_scorecard = scorecard

    # Ship the best pass, not merely the last.
    _restore(best_bodies)
    scorecard = best_scorecard

    if scorecard.get("needs_rewrite"):
        logger.warning(
            "writer.voice_review.still_off_voice",
            extra={"score": scorecard.get("score"),
                   "criticals": scorecard.get("critical_count")},
        )
    return scorecard


async def _default_judge(system: str, user: str, **kwargs):
    """Deferred import so the module stays importable (and testable) without
    the LLM client configured."""
    from modules.brief.llm import claude_json

    return await claude_json(system=system, user=user, **kwargs)
