"""Writer pure validators (M14 slice 3) — no egress.

Transcribes PRD #1 §5.8.8 (citable-claim C1–C9 detection + C7–C9 auto-soften),
§5.11 (CTA), §5.12 (key takeaways bounds), §5.13 (paragraph-length splitter +
abbreviation dict), §5.18 (title-case). The LLM retries these gate live in the
pipeline (slice 4); here are the deterministic detectors, the soften pass, and the
bound checks the pipeline calls before/after each call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import IntentType
from .templates import cta_template

CITATION_MARKER_RE = re.compile(r"\{\{cit_[0-9]+\}\}")
CTA_HARD_SALES_RE = re.compile(
    r"\b(buy|purchase|order)\s+now\b|\blimited\s+time\b|\bact\s+today\b", re.IGNORECASE
)
CTA_MAX_WORDS = 30
TAKEAWAY_MAX_WORDS = 25
TAKEAWAYS_MIN, TAKEAWAYS_MAX = 3, 5

# §5.13 abbreviations that carry a '.' but do NOT end a sentence.
_ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "mr.", "dr.", "vs.", "inc.", "u.s.", "u.k.",
}


def strip_markers(text: str) -> str:
    return CITATION_MARKER_RE.sub("", text)


def word_count(text: str) -> int:
    return len(strip_markers(text).split())


# ----- sentence / paragraph splitting (§5.13) -------------------------------


def split_sentences(text: str) -> list[str]:
    """Split on sentence-terminal `.?!` while skipping the abbreviation dict. Markdown
    link/code spans are left intact (we only suppress abbreviation periods)."""
    text = strip_markers(text).strip()
    if not text:
        return []
    # Protect abbreviation periods by temporarily masking them.
    masked = text
    for abbr in _ABBREVIATIONS:
        masked = re.sub(re.escape(abbr), abbr.replace(".", "\0"), masked, flags=re.IGNORECASE)
    parts = re.split(r"(?<=[.?!])\s+", masked)
    return [p.replace("\0", ".").strip() for p in parts if p.strip()]


def paragraph_violations(body: str, max_sentences: int = 4) -> list[dict]:
    """Paragraphs (blank-line separated) whose sentence count exceeds the cap.
    Returns `[{paragraph_index, sentence_count}]` (§5.13)."""
    out: list[dict] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    for idx, para in enumerate(paragraphs):
        n = len(split_sentences(para))
        if n > max_sentences:
            out.append({"paragraph_index": idx, "sentence_count": n})
    return out


# ----- citable-claim detection (§5.8.8 C1–C9) -------------------------------

_C1 = re.compile(r"\b\d[\d,.]*\s*(%|percent\b|pct\b|percentage points\b)")
_C2 = re.compile(r"([$€£]\s?\d[\d,.]*)|\b\d[\d,.]*\s*(million|billion|trillion)?\s*(USD|EUR|GBP)\b",
                 re.IGNORECASE)
_C3 = re.compile(r"\b(199\d|20\d\d)\b")
# Sentence-initial "According" must match without IGNORECASE (which would let the
# [A-Z] proper-noun requirement match lowercase too); spell both cases explicitly.
_C4 = re.compile(r"\b[Aa]ccording to\s+[A-Z]\w+|\b[A-Z]\w+\s+(reports|found|survey)\b")
_C5 = re.compile(r"\b(studies show|research shows|data shows|analysts predict)\b", re.IGNORECASE)
_C7_NOUNS = (r"cadence|window|cycle|interval|period|review|audit|refresh|sprint|cooldown"
             r"|lookback|horizon|grace period|onboarding")
# group(1) = unit; group(2) = the recommendation noun PHRASE (a run of rec-nouns, so
# "refresh cadence" is captured whole, not just "refresh"), after ≤2 filler words.
_C7 = re.compile(
    rf"\b\d+(?:[-–]to[-–]?\d+)?[-\s]?(day|week|month|year|hour|minute)s?\s+"
    rf"(?:\w+\s+){{0,2}}?((?:(?:{_C7_NOUNS})\s+)*(?:{_C7_NOUNS}))\b",
    re.IGNORECASE,
)
_C8_EVERY = re.compile(r"\bevery\s+\d+\s+(hours?|days?|weeks?|months?|quarters?|years?)\b", re.IGNORECASE)
_C8_NAMED = re.compile(
    r"\b(hourly|daily|weekly|biweekly|monthly|quarterly|annually)\s+"
    r"(audit|review|refresh|check|update|inspection|sync|reconciliation|cleanup|standup)\b",
    re.IGNORECASE,
)
_C9_RULE = re.compile(
    r"\b\d+%\s*(rule|threshold|target|cap|floor|ceiling|minimum|maximum|baseline|benchmark|cutoff)\b",
    re.IGNORECASE,
)
_C9_AIM = re.compile(r"\baim for\s+\d+%", re.IGNORECASE)
_C9_KEEP = re.compile(r"\bkeep\s+(it|under|below|above)\s+\d+%", re.IGNORECASE)


@dataclass
class ClaimMatch:
    sentence: str
    patterns: list[str] = field(default_factory=list)


def detect_citable_claims(text: str, *, entities: list[str] | None = None) -> list[ClaimMatch]:
    """Per-sentence C1–C9 detection. C6 = a sentence naming an `is_entity` SIE entity
    AND carrying a C1–C3 quantitative/temporal qualifier."""
    entities = [e.lower() for e in (entities or []) if e]
    out: list[ClaimMatch] = []
    for sent in split_sentences(text):
        hits: list[str] = []
        c1, c2, c3 = bool(_C1.search(sent)), bool(_C2.search(sent)), bool(_C3.search(sent))
        if c1:
            hits.append("C1")
        if c2:
            hits.append("C2")
        if c3:
            hits.append("C3")
        if _C4.search(sent):
            hits.append("C4")
        if _C5.search(sent):
            hits.append("C5")
        if entities and (c1 or c2 or c3) and any(e in sent.lower() for e in entities):
            hits.append("C6")
        if _C7.search(sent):
            hits.append("C7")
        if _C8_EVERY.search(sent) or _C8_NAMED.search(sent):
            hits.append("C8")
        if _C9_RULE.search(sent) or _C9_AIM.search(sent) or _C9_KEEP.search(sent):
            hits.append("C9")
        if hits:
            out.append(ClaimMatch(sentence=sent, patterns=hits))
    return out


# ----- auto-soften for operational claims (§5.8.8, C7–C9 only) --------------

_UNIT_PLURAL = {"day": "days", "week": "weeks", "month": "months", "year": "years",
                "hour": "hours", "minute": "minutes"}


def _soften_c7(text: str) -> tuple[str, int]:
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        unit = m.group(1).lower()
        noun = m.group(2)
        scale = "a brief window" if unit in ("day", "hour", "minute") else f"every few {_UNIT_PLURAL.get(unit, unit + 's')}"
        return f"a typical {noun} ({scale})"

    return _C7.sub(repl, text), n


def _soften_c8(text: str) -> tuple[str, int]:
    n = 0

    def every_repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"every few {m.group(1).rstrip('s')}s"

    def named_repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"a regular {m.group(2)}"

    text = _C8_EVERY.sub(every_repl, text)
    text = _C8_NAMED.sub(named_repl, text)
    return text, n


def _soften_c9(text: str) -> tuple[str, int]:
    n = 0

    def rule_repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"a small percentage {m.group(1)}"

    def aim_repl(_m: re.Match) -> str:
        nonlocal n
        n += 1
        return "aim for a moderate share"

    def keep_repl(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f"keep {m.group(1)} a moderate level"

    text = _C9_RULE.sub(rule_repl, text)
    text = _C9_AIM.sub(aim_repl, text)
    text = _C9_KEEP.sub(keep_repl, text)
    return text, n


def soften_operational_claims(text: str) -> tuple[str, int]:
    """Deterministic C7/C8/C9 hedge rewrite (§5.8.8). NEVER touches C1–C6 (softening a
    statistic/year/attribution mangles it). Returns `(softened_text, count_softened)`."""
    total = 0
    text, n = _soften_c7(text)
    total += n
    text, n = _soften_c8(text)
    total += n
    text, n = _soften_c9(text)
    total += n
    return text, total


def coverage_ratio(text: str, *, entities: list[str] | None = None) -> tuple[int, int, float]:
    """(citable_claims, cited_claims, ratio). In no_citations mode cited is always 0, so
    any section with citable claims is under the 0.5 floor → soften/flag path (§5.8.8)."""
    claims = detect_citable_claims(text, entities=entities)
    citable = len(claims)
    cited = sum(1 for c in claims if CITATION_MARKER_RE.search(c.sentence))
    ratio = (cited / citable) if citable else 1.0
    return citable, cited, ratio


# ----- CTA (§5.11) ----------------------------------------------------------


def validate_cta(cta: str) -> dict:
    """`{ok, too_long, hard_sales, word_count}`. The pipeline retries/truncates on a
    failing result."""
    wc = len(cta.split())
    return {
        "ok": wc <= CTA_MAX_WORDS and not CTA_HARD_SALES_RE.search(cta),
        "too_long": wc > CTA_MAX_WORDS,
        "hard_sales": bool(CTA_HARD_SALES_RE.search(cta)),
        "word_count": wc,
    }


def truncate_cta(cta: str, max_words: int = CTA_MAX_WORDS) -> str:
    words = cta.split()
    return cta if len(words) <= max_words else " ".join(words[:max_words]).rstrip(",;:") + "."


def fallback_cta(intent: IntentType) -> str:
    return cta_template(intent)


# ----- Key Takeaways bounds (§5.12) -----------------------------------------


def normalize_takeaways(takeaways: list[str]) -> tuple[list[str], str | None]:
    """Apply the count bounds (§5.12): truncate to 5 if over; accept down to 3; abort
    `key_takeaways_count_invalid` if <3. Returns `(list, abort_code|None)`. Over-length
    (>25-word) items are left for the pipeline's retry; not dropped here."""
    items = [t.strip() for t in takeaways if t and t.strip()]
    if len(items) > TAKEAWAYS_MAX:
        items = items[:TAKEAWAYS_MAX]
    if len(items) < TAKEAWAYS_MIN:
        return items, "key_takeaways_count_invalid"
    return items, None


def overlong_takeaways(takeaways: list[str]) -> list[int]:
    """Indices of takeaways exceeding the 25-word cap (§5.12 retry trigger)."""
    return [i for i, t in enumerate(takeaways) if len(t.split()) > TAKEAWAY_MAX_WORDS]


# ----- Title-case normalization (§5.18) -------------------------------------


def titlecase_heading(text: str) -> str:
    """Idempotent title-case pass (§5.18). Uses `titlecase` when available; falls back to
    a conservative capitalization that leaves the text unchanged on any failure (the PRD
    rule: never let the title-case pass break a heading — emit it anyway)."""
    if not text or not text.strip():
        return text
    try:
        from titlecase import titlecase
        return titlecase(text)
    except Exception:  # noqa: BLE001 — lib absent / unexpected -> emit unchanged
        return text
