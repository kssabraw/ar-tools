"""Brand-voice enforcement for the Fan-out writer.

The Fan-out writer (`pipeline.py`) is a self-contained, deliberately
client-agnostic mass generator — it had no brand-voice awareness at all, so
every client-linked article was written blind to the client's guide. This
module closes that gap without routing Fan-out through the heavy suite pipeline:
it reuses the suite's ONE definition of "did it sound like the client" (the
vendored, byte-identical `voice_card.py`) and runs the same eight-dimension
review + corrective-rewrite the interactive blog writer does — synchronously,
against the Fan-out's own LLM.

Two levers:
  * generation-time — `render_block(card)` injects the client's Voice & Audience
    Card into every prose prompt (the cheap, high-value lever: content starts
    on-voice, so fewer rewrites are needed).
  * post-pass — `enforce_voice(...)` scores the finished article against the
    guide, caps dimensions the deterministic checks disproved, and rewrites the
    worst-drifting body sections toward the voice bar (keeping the best pass).

The scorer / reviser PROMPTS are copied verbatim from
`pipeline-api/modules/writer/voice_review.py` and are parallel-maintained with
it (the suite already keeps the article-judge and page-judge rubrics in
parallel, not sync-guarded — see the content-quality notes). `voice_card.py` IS
sync-guarded byte-identical, so the scoring math, weights, threshold and
deterministic caps can never drift. Everything here is best-effort: any LLM /
parse failure leaves the article exactly as written and returns the
deterministic verdict, because a Fan-out article must never fail to generate
over a brand-voice check.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from . import voice_card as vcard

logger = logging.getLogger(__name__)

# --- tunables (mirror voice_review.py) --------------------------------------
_SCORE_HEAD_CHARS = 9000
_SCORE_TAIL_CHARS = 5000
_MAX_REVISED_SECTIONS = 6
MAX_VOICE_REVISION_PASSES = 3


def render_block(card: Optional[dict]) -> str:
    """The Voice & Audience Card as a high-priority prompt block, or '' when the
    client has no usable card. Thin passthrough so callers depend on one name."""
    if vcard.is_card_empty(card):
        return ""
    return vcard.render_voice_card_block(card)


# --- prose flattening (copied from voice_review.article_text/_truncate) -------
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


# --- prompts (verbatim from voice_review.py; parallel-maintained) ------------
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

_REVISE_SYSTEM = """You are revising an article's PROSE so it follows the client's brand guide. You are not rewriting the article.

HARD RULES:
- Change ONLY the wording. Keep every factual claim, statistic, citation marker, name, number and link exactly as it is.
- Do NOT change, reorder, add or remove headings. You are given specific sections by heading; return replacement BODY text for those headings only.
- Keep each section's approximate length and its structure — if the body has a bulleted list, the replacement has the same list with the same items, reworded.
- Keep the opening sentence of each section a direct, self-contained claim that names its subject. Rewriting for voice is not a licence for vague openers or pronouns that only resolve from an earlier sentence.
- Never introduce a term the guide forbids.

Return ONLY this JSON object, with one entry per section you were asked to revise:
{"sections": [{"heading": "<the heading exactly as given>", "body": "<the revised body>"}]}"""


def build_score_prompt(text: str, card: dict) -> str:
    return (
        vcard.render_voice_card_block(card)
        + "\n\n=== ARTICLE ===\n"
        + _truncate(text)
        + "\n\nScore the eight dimensions now."
    )


def build_revise_prompt(
    card: dict, scorecard: dict, sections: list[tuple[str, str]]
) -> str:
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
    be rewritten wherever they appear) and otherwise by length. Capped, because
    rewriting every section is a re-generation, not a revision.
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
        offends = bool(never_regex and never_regex.search(f"{heading}\n{body}"))
        candidates.append((0 if offends else 1, heading, body))
    if not candidates:
        return []
    candidates.sort(key=lambda c: (c[0], -len(c[2])))
    return [(heading, body) for _, heading, body in candidates[:_MAX_REVISED_SECTIONS]]


def apply_revisions(article: list, revisions: Any) -> int:
    """Replace section bodies in place from a revision response. Tolerant: an
    unrecognised heading / blank body / malformed payload is skipped rather than
    corrupting the article. Returns how many sections changed."""
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
            continue
        section.body = body.strip()
        if hasattr(section, "word_count"):
            section.word_count = len(body.split())
        applied += 1
    return applied


def _rank_key(scorecard: Optional[dict]) -> tuple:
    """Keep-best ranking: fewest critical violations first, then highest score."""
    sc = scorecard or {}
    criticals = sc.get("critical_count") or 0
    score = sc.get("score")
    return (-criticals, score if isinstance(score, (int, float)) else -1.0)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(text: str) -> Any:
    """Tolerantly pull the JSON object out of a plain-text completion. The
    prompts say "Return ONLY this JSON object", but models occasionally wrap it
    in prose or a ```json fence — grab the outermost {...} and parse."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def score_voice(text: str, card: dict, section_llm) -> dict:
    """The eight scored dimensions, or `{}` when the call/parse fails.

    `{}` is honest and handled by `voice_card.voice_scorecard`: the scorecard
    marks itself `analysis="deterministic_only"` and the regex findings stand.
    """
    if vcard.is_card_empty(card) or not (text or "").strip():
        return {}
    try:
        raw = section_llm.complete_text(
            system=_SCORE_SYSTEM, user=build_score_prompt(text, card),
            purpose="fanout_voice_score", max_tokens=2500, temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("fanout.voice.score_failed",
                       extra={"error_type": type(exc).__name__, "error": str(exc)[:300]})
        return {}
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, dict) else {}


def enforce_voice(
    title: str, article: list, card: Optional[dict], section_llm,
    *, max_passes: int = MAX_VOICE_REVISION_PASSES,
) -> Optional[dict]:
    """Score the finished article against the guide and revise it if it falls
    short. Mutates `article` (section bodies) in place. Returns the scorecard,
    or None when the client has no usable card.

    Sync port of `voice_review.review_article_voice` for the Fan-out's sync LLM.
    Never raises — a failure at any step leaves the article exactly as written
    and still returns the deterministic verdict.
    """
    if vcard.is_card_empty(card):
        return None

    def _measure() -> tuple[str, list[dict]]:
        text = article_text(title, article)
        return text, vcard.check_voice_compliance(text, card)

    text, violations = _measure()
    dimensions = score_voice(text, card, section_llm)
    scorecard = vcard.voice_scorecard(dimensions, violations)

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
        try:
            raw = section_llm.complete_text(
                system=_REVISE_SYSTEM,
                user=build_revise_prompt(card, scorecard, targets),
                purpose="fanout_voice_revise", max_tokens=8000, temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("fanout.voice.revise_failed",
                           extra={"error_type": type(exc).__name__, "error": str(exc)[:300]})
            break
        if not apply_revisions(article, _parse_json(raw)):
            break
        text, violations = _measure()
        dimensions = score_voice(text, card, section_llm)
        scorecard = vcard.voice_scorecard(dimensions, violations)
        if _rank_key(scorecard) > _rank_key(best_scorecard):
            best_bodies = _snapshot()
            best_scorecard = scorecard

    # Ship the best pass, not merely the last.
    _restore(best_bodies)
    if best_scorecard.get("needs_rewrite"):
        logger.info("fanout.voice.still_off_voice",
                    extra={"score": best_scorecard.get("score"),
                           "criticals": best_scorecard.get("critical_count")})
    return best_scorecard
