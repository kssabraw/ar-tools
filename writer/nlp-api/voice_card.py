"""Brand Voice & Audience Card — the client's own guide, made enforceable.

Every generator in the suite already *receives* the client's brand voice and
ICP: they're rendered into the prompt as prose blocks. That turned out not to
be enough. Three things beat them in practice:

  1. The SEO checklist told the model its ICP, derived from a keyword
     modifier (`_detect_icp_from_keyword`) — a canned guess presented as a
     mandate, while the client's real ICP sat earlier as background.
  2. The generation system prompt carries expression-level defaults
     (prefer third person over "we/our", fixed title formula, CTA tone) that
     contradict a guide specifying otherwise — and it sits in the cached
     system slot, which reads as more authoritative.
  3. Nothing scored voice adherence, so drift was invisible. Pages scored
     "good" on eight SEO/AEO engines while failing a human voice audit.

This module is the fix's shared core: a compact, structured card distilled
once per guide revision, rendered as a late high-priority prompt block, and
— crucially — checked **deterministically** in Python after generation. The
LLM judge can be talked out of a verdict; a word-boundary regex cannot.

Split of responsibility (mirrors `ecommerce_facts.py`):
  - everything here is pure and unit-tested
  - the one Anthropic call lives in `main.py::_distill_voice_card`

Severity model:
  - `critical`  → a never-use term appeared. Hard fail; the caller runs a
    corrective pass and the page is flagged until it's gone.
  - `warning`   → must-use term absent, grammatical person contradicts the
    guide, no CTA resembles the guide's language. Reported and fed to the
    corrective pass, never blocking on its own.

The banned/discouraged bar is deliberately identical to the blog writer's
(`pipeline-api/modules/writer/distillation.py`): "banned" requires literal
prohibitive language in the guide, because a false positive here blocks a
page. Anything softer is "discouraged" and only ever warns.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

# ── Card shape ─────────────────────────────────────────────────────────────
# A plain dict rather than a pydantic model: the card crosses a service
# boundary (platform-api distills + caches, nlp-api consumes) and is stored
# as jsonb, so JSON-native is the least friction.

_EMPTY_CARD: dict[str, Any] = {
    "brand_name": "",
    "tone_adjectives": [],
    "person": "",
    "voice_directives": [],
    "sentence_rhythm": "",
    "must_use_terms": [],
    "never_use_terms": [],
    "discouraged_terms": [],
    "cta_language": [],
    "audience_label": "",
    "audience_summary": "",
    "audience_pain_points": [],
    "audience_triggers": [],
    "audience_motivations": [],
    "audience_objections": [],
}


def empty_card() -> dict[str, Any]:
    """A fresh, all-empty card. Callers mutate their own copy."""
    return json.loads(json.dumps(_EMPTY_CARD))


DISTILL_SYSTEM = """You are a categorization-only LLM. You extract brand voice and audience signals that are STATED in the provided documents. You never invent, infer, or improve on them.

Output a single JSON object matching this exact schema:
{
  "brand_name": string (the name the brand uses for itself, verbatim; "" if not stated),
  "tone_adjectives": [string, max 10],
  "person": "first" | "third" | "" (does the guide tell the writer to speak as "we/our" (first) or to name the brand in third person (third)? "" if the guide does not say),
  "voice_directives": [string, max 8, each <=200 chars - the guide's concrete HOW-TO-WRITE rules],
  "sentence_rhythm": string (max 200 chars - what the guide says about sentence length/rhythm/cadence; "" if unstated),
  "must_use_terms": [string, max 15 - phrasings the guide REQUIRES or names as preferred],
  "never_use_terms": [string, max 30 - see the HIGH BAR rule below],
  "discouraged_terms": [string, max 20 - softer "avoid/prefer X over Y" preferences],
  "cta_language": [string, max 8 - the call-to-action phrasings the guide or ICP calls for, verbatim],
  "audience_label": string (max 120 - a short name for the primary customer, e.g. "Melbourne homeowner with a 20+ year old tile roof"),
  "audience_summary": string (max 300),
  "audience_pain_points": [string, max 6],
  "audience_triggers": [string, max 6 - what makes them search RIGHT NOW],
  "audience_motivations": [string, max 6],
  "audience_objections": [string, max 6 - what makes them hesitate to buy]
}

CRITICAL RULES:
- Extract verbatim wherever possible. Do NOT paraphrase a rule into your own words.
- never_use_terms has a HIGH BAR: include a term ONLY when the document uses literal prohibitive language about it - "never use", "do not use", "banned", "prohibited", "must not appear", "absolutely not", or equivalent. A page will be BLOCKED when one of these appears, so a false positive is expensive.
- discouraged_terms is for every softer preference - "avoid", "we prefer X over Y", "try not to", "use sparingly", "lean away from". When torn between never_use and discouraged, choose discouraged.
- person: answer "first" only if the guide actually asks the writer to use we/our/us, and "third" only if it asks for the brand to be named instead. If the guide is silent, return "".
- tone_adjectives, voice_directives, sentence_rhythm, must_use_terms, never_use_terms, discouraged_terms come from the BRAND GUIDE.
- audience_* and cta_language come from the ICP (cta_language may also come from the brand guide when it specifies CTA wording).
- If a field has no basis in the source documents, return an empty array, empty string, or "". Never fill a field to look complete."""


def build_distill_prompt(brand_guide_text: str, icp_text: str) -> str:
    """User prompt for the distillation call. Kept pure so tests can assert
    that both documents actually reach the model."""
    parts = [
        "=== BRAND GUIDE ===",
        (brand_guide_text or "").strip() or "(none provided)",
        "",
        "=== IDEAL CUSTOMER PROFILE ===",
        (icp_text or "").strip() or "(none provided)",
        "",
        "Distill into the voice & audience card JSON object now.",
    ]
    return "\n".join(parts)


def parse_voice_card(raw: Any) -> dict[str, Any]:
    """Coerce a model response into a well-formed card. Never raises — a
    malformed field degrades to its empty default rather than poisoning
    every downstream consumer (the same lesson as
    `brand_voice_service._coerce_vocabulary`)."""
    card = empty_card()
    if not isinstance(raw, dict):
        return card

    def _str(key: str, cap: int) -> str:
        val = raw.get(key)
        return str(val).strip()[:cap] if isinstance(val, (str, int, float)) else ""

    def _list(key: str, cap: int, item_cap: int = 200) -> list[str]:
        val = raw.get(key)
        if not isinstance(val, list):
            return []
        out: list[str] = []
        for item in val:
            if not isinstance(item, (str, int, float)):
                continue
            text = str(item).strip()[:item_cap]
            if text:
                out.append(text)
        return out[:cap]

    person = _str("person", 10).lower()
    card["person"] = person if person in ("first", "third") else ""

    card["brand_name"] = _str("brand_name", 120)
    card["sentence_rhythm"] = _str("sentence_rhythm", 200)
    card["audience_label"] = _str("audience_label", 120)
    card["audience_summary"] = _str("audience_summary", 300)

    card["tone_adjectives"] = _list("tone_adjectives", 10, 60)
    card["voice_directives"] = _list("voice_directives", 8)
    card["must_use_terms"] = _list("must_use_terms", 15, 80)
    card["never_use_terms"] = _sanitize_never_use(_list("never_use_terms", 30, 80))
    card["discouraged_terms"] = _list("discouraged_terms", 20, 80)
    card["cta_language"] = _list("cta_language", 8, 120)
    card["audience_pain_points"] = _list("audience_pain_points", 6)
    card["audience_triggers"] = _list("audience_triggers", 6)
    card["audience_motivations"] = _list("audience_motivations", 6)
    card["audience_objections"] = _list("audience_objections", 6)
    return card


# Words too short or too common to ever be safe as a hard block. A guide that
# genuinely bans "we" needs the `person` field, not a regex that fails every
# page ever written.
_NEVER_USE_STOPLIST = {
    "we", "our", "us", "you", "your", "the", "and", "for", "with", "that",
    "this", "it", "is", "are", "was", "be", "to", "of", "in", "on", "at",
    "a", "an", "or", "as", "by", "from", "not", "no", "yes",
}
_MIN_NEVER_USE_CHARS = 3


def _sanitize_never_use(terms: list[str]) -> list[str]:
    """Drop terms that would make the hard block fire on every page. A
    stopword or two-character 'banned term' is always a distillation
    artifact, never a real brand rule."""
    out: list[str] = []
    for term in terms:
        cleaned = term.strip()
        if len(cleaned) < _MIN_NEVER_USE_CHARS:
            continue
        if cleaned.lower() in _NEVER_USE_STOPLIST:
            continue
        out.append(cleaned)
    return out


def is_card_empty(card: Optional[dict]) -> bool:
    """True when there is nothing to enforce. Callers fall back to their
    prior behaviour rather than emitting an empty guidance block.

    `person` counts: a guide that says only "write as we/our" is precisely the
    rule the generator's third-person default was overriding, so a card
    carrying nothing else is still worth rendering and checking."""
    if not card:
        return True
    return not any(card.get(key) for key in _EMPTY_CARD)


def card_fingerprint(brand_guide_text: str, icp_text: str) -> str:
    """Stable key for caching a distilled card against the raw documents it
    came from. Re-distillation happens when the guide changes, not per page."""
    digest = hashlib.sha256()
    digest.update((brand_guide_text or "").strip().encode("utf-8"))
    digest.update(b"\x00")
    digest.update((icp_text or "").strip().encode("utf-8"))
    return digest.hexdigest()


# ── Prompt rendering ───────────────────────────────────────────────────────

def render_voice_card_block(card: Optional[dict]) -> str:
    """The late, high-priority prompt block.

    Placed after the SEO checklist and structure guidance so it carries the
    recency the guide was previously denied, and worded to win the specific
    conflicts we found: grammatical person, CTA phrasing, word choice, tone.
    Layout requirements deliberately still win — a warm brand still writes
    answer-first openings and short paragraphs, it just does so in its own
    voice."""
    if is_card_empty(card):
        return ""
    card = card or {}
    lines: list[str] = [
        "BRAND VOICE & AUDIENCE — THE CLIENT'S OWN GUIDE (HIGHEST PRIORITY FOR EXPRESSION)",
        "",
        "These rules come from this client's written brand guide and ICP. Where ANY earlier",
        "default in this prompt conflicts with them on word choice, tone, grammatical person,",
        "or CTA phrasing, THESE RULES WIN — including the default preference for third person",
        "and the default CTA wording. Structural requirements (answer-first openings, paragraph",
        "length, required lists/table, headings, schema) still apply: express them in this voice",
        "rather than abandoning them.",
        "",
    ]

    if card.get("brand_name"):
        lines.append(f"Brand: {card['brand_name']}")
    if card.get("tone_adjectives"):
        lines.append(f"Tone (every section must read this way): {', '.join(card['tone_adjectives'])}")

    person = card.get("person")
    if person == "first":
        lines.append(
            "Grammatical person: FIRST PERSON. Write as \"we/our\". This OVERRIDES the "
            "default preference for naming the brand in third person. Keep the subject "
            "explicit in the opening claim of each section (\"We repair…\" or the brand "
            "name where it reads better), never a bare pronoun like \"it\" or \"this\"."
        )
    elif person == "third":
        lines.append(
            "Grammatical person: THIRD PERSON. Name the brand rather than writing \"we/our\"."
        )

    if card.get("sentence_rhythm"):
        lines.append(f"Sentence rhythm: {card['sentence_rhythm']}")

    if card.get("voice_directives"):
        lines.append("")
        lines.append("Voice rules — follow every one:")
        for directive in card["voice_directives"]:
            lines.append(f"  - {directive}")

    if card.get("must_use_terms"):
        lines.append("")
        lines.append(
            "REQUIRED phrasing — use these terms, in these words: "
            + ", ".join(f'"{t}"' for t in card["must_use_terms"])
        )
    if card.get("never_use_terms"):
        lines.append(
            "FORBIDDEN — these words/phrases must NOT appear anywhere on the page "
            "(the page is rejected if they do): "
            + ", ".join(f'"{t}"' for t in card["never_use_terms"])
        )
    if card.get("discouraged_terms"):
        lines.append(
            "Avoid where possible (softer than forbidden): "
            + ", ".join(f'"{t}"' for t in card["discouraged_terms"])
        )

    audience_bits = [
        ("Primary customer", card.get("audience_label")),
        ("Who they are", card.get("audience_summary")),
    ]
    audience_lists = [
        ("What they're worried about (address these directly)", card.get("audience_pain_points")),
        ("What makes them search right now", card.get("audience_triggers")),
        ("What they actually want (lead with these)", card.get("audience_motivations")),
        ("Why they hesitate (answer these on the page)", card.get("audience_objections")),
    ]
    if any(v for _, v in audience_bits) or any(v for _, v in audience_lists):
        lines.append("")
        lines.append("WRITE TO THIS CUSTOMER — not a generic homeowner:")
        for label, value in audience_bits:
            if value:
                lines.append(f"  {label}: {value}")
        for label, values in audience_lists:
            if values:
                lines.append(f"  {label}: {'; '.join(values)}")

    if card.get("cta_language"):
        lines.append("")
        lines.append(
            "CTA language — every call to action must use this client's wording, NOT the "
            "generic defaults elsewhere in this prompt: "
            + " / ".join(f'"{c}"' for c in card["cta_language"])
        )

    return "\n".join(lines)


def resolve_icp_directives(
    card: Optional[dict],
    fallback: tuple[str, str, str],
) -> tuple[str, str, str]:
    """Return `(icp_label, tone_instruction, cta_instruction)` for the SEO
    checklist's ICP ALIGNMENT block.

    The checklist used to state a keyword-derived guess here and the system
    prompt told the model to obey it, which is how a real 6,900-character ICP
    lost to a three-word heuristic. When the client has an ICP on file its
    card wins; `fallback` (the keyword heuristic) fills any field the card
    can't, so a client with no ICP behaves exactly as before."""
    fb_label, fb_tone, fb_cta = fallback
    if is_card_empty(card):
        return fallback
    card = card or {}

    label = card.get("audience_label") or card.get("audience_summary") or fb_label

    tone_parts: list[str] = []
    if card.get("tone_adjectives"):
        tone_parts.append(", ".join(card["tone_adjectives"]))
    if card.get("audience_motivations"):
        tone_parts.append(
            "speak to what they want: " + "; ".join(card["audience_motivations"][:3])
        )
    if card.get("audience_pain_points"):
        tone_parts.append(
            "and what worries them: " + "; ".join(card["audience_pain_points"][:3])
        )
    tone = " — ".join(tone_parts) if tone_parts else fb_tone

    cta = (
        " / ".join(f'"{c}"' for c in card["cta_language"])
        if card.get("cta_language")
        else fb_cta
    )
    return label, tone, cta


# ── Deterministic compliance checks ────────────────────────────────────────
# No LLM. These are the checks that cannot be argued out of a verdict, and
# they are what makes "we checked" a fact rather than a claim.

_FIRST_PERSON_RE = re.compile(r"\b(?:we|we're|we've|we'll|our|ours|us)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z']+")

# Density is per 1,000 words. A page written in first person lands well above
# 6; a strictly third-person page lands near 0. The bands are set wide so
# ordinary prose variation never trips them — these warn, they don't block,
# but a noisy warning gets ignored and stops being a check at all.
_FIRST_PERSON_ABSENT_MAX = 1.0    # card says "first" but page reads third
_THIRD_PERSON_EXCEEDED_MIN = 6.0  # card says "third" but page reads first


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def build_term_regex(terms: list[str]) -> Optional[re.Pattern]:
    """Case-insensitive word-boundary alternation over `terms`.

    `\\b` is only meaningful next to a word character, so a term that starts
    or ends with punctuation (e.g. "100% guaranteed") gets the boundary
    dropped on that side rather than silently never matching."""
    cleaned = [t.strip() for t in (terms or []) if t and t.strip()]
    if not cleaned:
        return None
    parts: list[str] = []
    for term in cleaned:
        escaped = re.escape(term)
        prefix = r"\b" if term[0].isalnum() or term[0] == "_" else ""
        suffix = r"\b" if term[-1].isalnum() or term[-1] == "_" else ""
        parts.append(f"{prefix}{escaped}{suffix}")
    return re.compile("(?:" + "|".join(parts) + ")", re.IGNORECASE)


def _significant_tokens(phrase: str) -> list[str]:
    return [
        t.lower()
        for t in _WORD_RE.findall(phrase or "")
        if len(t) > 2 and t.lower() not in _NEVER_USE_STOPLIST
    ]


def _cta_present(page_text_lower: str, cta: str) -> bool:
    """A CTA counts as honoured on a loose match: its normalized form appears,
    or at least two of its distinctive words do. Exact-phrase matching would
    fail on every natural variation ("Call now" vs "Call us now"), and a CTA
    check that cries wolf is a check nobody reads."""
    normalized = " ".join((cta or "").lower().split())
    if normalized and normalized in page_text_lower:
        return True
    tokens = _significant_tokens(cta)
    if not tokens:
        return False
    hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", page_text_lower))
    return hits >= min(2, len(tokens))


def check_voice_compliance(page_text: str, card: Optional[dict]) -> list[dict]:
    """Deterministic voice/ICP audit of a generated page's visible text.

    `page_text` must be the rendered text (title included), not raw HTML —
    otherwise class names and URLs match terms that never reach the reader.

    Returns a list of violation dicts:
      `{check, severity, message, terms?, detail?}`
    Empty list = the page passed every check we can make without an LLM.
    """
    if is_card_empty(card) or not (page_text or "").strip():
        return []
    card = card or {}
    text = page_text
    text_lower = " ".join(text.lower().split())
    violations: list[dict] = []

    # 1. Forbidden terms — the only critical check.
    never_regex = build_term_regex(card.get("never_use_terms") or [])
    if never_regex:
        found = sorted({m.group(0).lower() for m in never_regex.finditer(text)})
        if found:
            violations.append({
                "check": "never_use_terms",
                "severity": "critical",
                "terms": found,
                "message": (
                    "The brand guide forbids these words and they appear on the page: "
                    + ", ".join(f'"{t}"' for t in found)
                ),
            })

    # 2. Required phrasing absent.
    missing_required: list[str] = []
    for term in card.get("must_use_terms") or []:
        term_regex = build_term_regex([term])
        if term_regex is None or not term_regex.search(text):
            missing_required.append(term)
    if missing_required:
        violations.append({
            "check": "must_use_terms",
            "severity": "warning",
            "terms": missing_required,
            "message": (
                "The brand guide requires this phrasing and it never appears: "
                + ", ".join(f'"{t}"' for t in missing_required)
            ),
        })

    # 3. Grammatical person contradicts the guide.
    words = _word_count(text)
    if words >= 100:
        first_person_hits = len(_FIRST_PERSON_RE.findall(text))
        density = (first_person_hits / words) * 1000
        person = card.get("person")
        if person == "first" and density <= _FIRST_PERSON_ABSENT_MAX:
            violations.append({
                "check": "person",
                "severity": "warning",
                "detail": f"{first_person_hits} first-person words across {words} ({density:.1f}/1k)",
                "message": (
                    "The brand guide specifies first person (we/our) but the page is "
                    "written in third person."
                ),
            })
        elif person == "third" and density >= _THIRD_PERSON_EXCEEDED_MIN:
            violations.append({
                "check": "person",
                "severity": "warning",
                "detail": f"{first_person_hits} first-person words across {words} ({density:.1f}/1k)",
                "message": (
                    "The brand guide specifies third person (name the brand) but the page "
                    "leans on we/our."
                ),
            })

    # 4. CTA language ignored entirely.
    ctas = card.get("cta_language") or []
    if ctas and not any(_cta_present(text_lower, c) for c in ctas):
        violations.append({
            "check": "cta_language",
            "severity": "warning",
            "terms": list(ctas),
            "message": (
                "No call to action on the page resembles the client's CTA language: "
                + " / ".join(f'"{c}"' for c in ctas)
            ),
        })

    return violations


def has_critical(violations: Optional[list[dict]]) -> bool:
    """True when the page must not ship as-is."""
    return any(v.get("severity") == "critical" for v in (violations or []))


def violations_to_corrections(violations: Optional[list[dict]]) -> str:
    """Render violations as explicit correction instructions for a rewrite
    pass. Deterministic findings make far better rewrite input than a score:
    they name the exact word to remove."""
    if not violations:
        return ""
    lines = [
        "BRAND VOICE CORRECTIONS — HIGHEST PRIORITY. The previous draft broke this "
        "client's brand guide. Fix EXACTLY these, changing nothing else about the "
        "page's structure, keywords, entities, or schema:",
    ]
    for violation in violations:
        marker = "MUST FIX" if violation.get("severity") == "critical" else "Fix"
        lines.append(f"  - [{marker}] {violation.get('message', '')}")
        if violation.get("check") == "never_use_terms":
            lines.append(
                "    Remove every occurrence — including headings, the title, FAQ answers, "
                "table cells, and the schema block — and rephrase in the brand's own words."
            )
        elif violation.get("check") == "must_use_terms":
            lines.append(
                "    Work each of these in naturally where it fits the meaning; do not "
                "bolt them on as a list."
            )
        elif violation.get("check") == "person":
            lines.append(
                "    Rewrite the affected sentences. Keep every opening claim self-contained "
                "and its subject explicit — switching person is not a licence for pronouns "
                "that only resolve from an earlier sentence."
            )
        elif violation.get("check") == "cta_language":
            lines.append(
                "    Rewrite every CTA using the client's wording above."
            )
    return "\n".join(lines)


def compliance_summary(violations: Optional[list[dict]]) -> dict:
    """Compact, storable verdict for persistence and the UI."""
    violations = violations or []
    return {
        "passed": not violations,
        "critical_count": sum(1 for v in violations if v.get("severity") == "critical"),
        "warning_count": sum(1 for v in violations if v.get("severity") == "warning"),
        "violations": violations,
    }


# ── The voice scorecard ────────────────────────────────────────────────────
# Brand voice is scored SEPARATELY from SEO/AEO rather than folded into that
# composite as one weighted engine. Two reasons:
#
#   * A single 10% engine cannot move a composite enough to matter — a page
#     scoring 40 on voice loses five points against one scoring 90, so it still
#     reads "good". Hiding voice inside an SEO number is the same mistake that
#     let it be ignored in the first place.
#   * "Voice is 62" is not actionable. Which part — the tone, the sentence
#     rhythm, the fact that it never addresses what the customer is worried
#     about? Sub-dimensions make the number tell you what to fix.
#
# Weights favour the dimensions a reader actually notices (tone, style,
# vocabulary, whether it speaks to them) over the mechanical ones.

VOICE_DIMENSIONS: dict[str, dict] = {
    "tone":            {"label": "Tone & personality", "weight": 0.15},
    "writing_style":   {"label": "Writing style",      "weight": 0.15},
    "person":          {"label": "Grammatical person", "weight": 0.10},
    "vocabulary":      {"label": "Vocabulary",         "weight": 0.15},
    "audience_fit":    {"label": "Audience fit",       "weight": 0.15},
    "pain_points":     {"label": "Pain points & objections", "weight": 0.10},
    "cta_fit":         {"label": "Call-to-action fit", "weight": 0.10},
    "distinctiveness": {"label": "Distinctiveness",    "weight": 0.10},
}

# A dimension the guide says nothing about must not drag the score down — a
# guide that never mentions sentence rhythm is not a page failing at it. The
# scorer marks those `applicable: false` and the remaining weights renormalize.
VOICE_PASS_THRESHOLD = 80.0

# Deterministic findings outrank the judge on the things a regex can settle.
# Without this a scorer can call vocabulary "strong" on a page that provably
# contains a forbidden word.
_DETERMINISTIC_CAPS = {
    "never_use_terms": ("vocabulary", 40.0),
    "must_use_terms":  ("vocabulary", 70.0),
    "person":          ("person", 40.0),
    "cta_language":    ("cta_fit", 50.0),
}


def voice_band(score: Optional[float]) -> str:
    """Plain-language band for a voice score. Deliberately not the SEO status
    vocabulary — this answers "does it sound like the client", not "will it
    rank"."""
    if score is None:
        return "not_scored"
    if score >= 90:
        return "on_voice"
    if score >= VOICE_PASS_THRESHOLD:
        return "mostly_on_voice"
    if score >= 60:
        return "drifting"
    return "off_voice"


def _dimension_score(raw: Any) -> tuple[Optional[float], bool]:
    """Pull `(score, applicable)` out of one scorer dimension, tolerantly."""
    if not isinstance(raw, dict):
        return None, False
    if raw.get("applicable") is False:
        return None, False
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None, False
    return max(0.0, min(100.0, float(score))), True


def apply_deterministic_caps(
    dimensions: dict, violations: Optional[list[dict]]
) -> dict:
    """Lower any dimension the deterministic checks have already disproved.

    Returns a new dimensions dict; never raises the score, only caps it, and
    records why on the dimension so the UI can show the reason.
    """
    out = {key: dict(value) if isinstance(value, dict) else value
           for key, value in (dimensions or {}).items()}
    for violation in violations or []:
        mapping = _DETERMINISTIC_CAPS.get(violation.get("check", ""))
        if not mapping:
            continue
        key, cap = mapping
        entry = out.get(key)
        if not isinstance(entry, dict):
            continue
        score, applicable = _dimension_score(entry)
        if not applicable or score is None or score <= cap:
            continue
        entry["score"] = cap
        entry["capped_by_check"] = violation.get("check")
    return out


def compute_voice_score(dimensions: Optional[dict]) -> Optional[float]:
    """Weighted 0-100 across the applicable dimensions, renormalized.

    None when nothing could be scored — honest, and distinct from zero.
    """
    total_weight = 0.0
    total = 0.0
    for key, meta in VOICE_DIMENSIONS.items():
        score, applicable = _dimension_score((dimensions or {}).get(key))
        if not applicable or score is None:
            continue
        total += score * meta["weight"]
        total_weight += meta["weight"]
    if total_weight <= 0:
        return None
    return round(total / total_weight, 1)


def build_voice_deficiencies(dimensions: Optional[dict]) -> list[dict]:
    """The failing dimensions, worst first, as rewrite input.

    Shaped like the SEO scorer's deficiencies so the rewrite prompt can render
    them the same way.
    """
    out: list[dict] = []
    for key, meta in VOICE_DIMENSIONS.items():
        entry = (dimensions or {}).get(key)
        score, applicable = _dimension_score(entry)
        if not applicable or score is None or score >= VOICE_PASS_THRESHOLD:
            continue
        entry = entry if isinstance(entry, dict) else {}
        out.append({
            "engine": meta["label"],
            "engine_key": key,
            "score": score,
            "issues": [i for i in (entry.get("issues") or []) if i],
            "recommendations": [r for r in (entry.get("recommendations") or []) if r],
            "evidence": entry.get("evidence") or "",
        })
    return sorted(out, key=lambda d: d["score"])


def voice_scorecard(
    dimensions: Optional[dict], violations: Optional[list[dict]]
) -> dict:
    """The complete, storable voice verdict: headline score, band, per-dimension
    detail, deterministic violations, and the failing dimensions to rewrite.

    This is what gets persisted and rendered — one object so the page's voice
    verdict can't drift apart across surfaces.
    """
    capped = apply_deterministic_caps(dimensions or {}, violations)
    score = compute_voice_score(capped)
    summary = compliance_summary(violations)
    deficiencies = build_voice_deficiencies(capped)
    # How much of the analysis actually ran. The deterministic checks need no
    # network and always run; the scored dimensions come from an LLM call that
    # can fail. A page whose scoring call died must not be indistinguishable
    # from a clean one — "we could not check this" is a different answer from
    # "this passed", and only one of them is safe to publish on.
    analysis = "full" if score is not None else "deterministic_only"
    return {
        **summary,
        "analysis": analysis,
        "score": score,
        "band": voice_band(score),
        "dimensions": {
            key: {
                "label": meta["label"],
                "weight": meta["weight"],
                **(capped.get(key) if isinstance(capped.get(key), dict) else {}),
            }
            for key, meta in VOICE_DIMENSIONS.items()
            if key in (capped or {})
        },
        "deficiencies": deficiencies,
        # The page needs work when a regex caught something OR the judge scored
        # it below the bar. Either is enough to earn a corrective rewrite.
        "needs_rewrite": bool(summary["critical_count"])
        or (score is not None and score < VOICE_PASS_THRESHOLD),
    }


def unanalyzed_scorecard(reason: str) -> dict:
    """The verdict for a page we could not check at all.

    Reached when the client HAS a brand guide but it could not be distilled
    into a card — so there was nothing to check against, even though there
    should have been. Emitted rather than returning nothing, because a page
    that silently skipped its brand-voice analysis must not look identical to
    one that passed it.

    `needs_rewrite` is False: there is no finding to rewrite toward, and
    burning corrective passes against an unknown would be guesswork.
    """
    return {
        "passed": False,
        "critical_count": 0,
        "warning_count": 0,
        "violations": [],
        "analysis": "not_analyzed",
        "reason": reason,
        "score": None,
        "band": "not_scored",
        "dimensions": {},
        "deficiencies": [],
        "needs_rewrite": False,
    }


def voice_deficiency_text(deficiencies: Optional[list[dict]]) -> str:
    """Render failing dimensions as rewrite instructions."""
    if not deficiencies:
        return ""
    lines = [
        "BRAND VOICE — the page does not yet sound like this client. Fix each of "
        "these, changing nothing about its structure, keywords, entities, or schema:",
    ]
    for deficiency in deficiencies:
        # `:g` so a whole score renders as "45/100", not "45.0/100".
        lines.append(f"  {deficiency['engine']} — scored {deficiency['score']:g}/100")
        for issue in (deficiency.get("issues") or [])[:4]:
            lines.append(f"    - {issue}")
        for rec in (deficiency.get("recommendations") or [])[:4]:
            lines.append(f"    → {rec}")
        if deficiency.get("evidence"):
            lines.append(f"    (example from the page: \"{deficiency['evidence']}\")")
    return "\n".join(lines)
