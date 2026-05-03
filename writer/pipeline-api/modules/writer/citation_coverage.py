r"""Step 4F.1 — Citable-Claim Detection + Coverage (Writer PRD §4F.1, R7).

Phase 4 introduces the whole validator. Base patterns C1–C6 come from
the writer PRD §4F.1 (Content Quality PRD R7). C7–C9 are NEW in Phase 4
to catch the audited "unsourced operational claims" failure mode —
durations / frequencies / operational percentages stated as fact
without an adjacent citation marker.

Detection patterns (sentence-level — a sentence containing any C-pattern
counts as ONE citable claim):

| ID | Pattern (informal description) |
|----|-------------------------------|
| C1 | A numeral with `%` / `percent` / `pct` / `percentage points` |
| C2 | A numeral with currency (`$100M`, `1.2 billion USD`, `€50`) |
| C3 | A four-digit year between 1990–2099 used as a date |
| C4 | `according to <ProperNoun>` / `<ProperNoun> reports/found/survey` |
| C5 | `studies show` / `research shows` / `data shows` / `analysts predict` |
| C6 | Sentence with an SIE entity (caller passes entity list) AND a |
|    | quantitative/temporal qualifier from C1–C3 |
| C7 | Duration-as-recommendation (NEW in Phase 4): a numeric duration |
|    | followed by `cadence` / `window` / `cycle` / `interval` etc. |
| C8 | Frequency-as-recommendation (NEW): `every <N> <unit>`, or |
|    | `(weekly\|monthly\|quarterly\|biweekly\|annually) <action>` |
| C9 | Operational-percentage (NEW): `<N>% rule/threshold/target/cap` |
|    | or `aim for <N>%` |

Coverage rule (per PRD R7): per-section, ≥ 50% of detected citable
claims must be followed by a `{{cit_N}}` marker on the same sentence.
Retry policy:
  1. Compute coverage. If < 50%, retry the section ONCE with a
     coverage-retry directive listing the uncited claims and asking
     the LLM to either add a marker (from the available pool) or
     rewrite the sentence to remove the specific claim.
  2. After retry, recompute coverage. If still < 50%, run the
     auto-soften pass on the section body — it deterministically
     rewrites C7/C8/C9-style operational claims to hedge phrasing
     ("4-to-6 week refresh cadence" → "a typical refresh cadence
     (every few weeks)"). Auto-soften does NOT touch C1-C6 claims —
     those are statistics/years/source-attributed facts where
     softening would introduce more harm than it fixes.
  3. Section is accepted, with under-cited sections + softened spans
     surfaced in metadata.

The auto-soften table is intentionally small in v1 — adds entries as
production data shows which patterns recur. Each entry is a regex +
soften function so soften logic can be deterministic and reviewable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# Citation marker (matches Step 4F's marker convention).
_MARKER_RE = re.compile(r"\{\{cit_\d+\}\}")

# Sentence splitter — finds sentence boundaries AND tracks the
# `{{cit_N}}` marker (if any) attached immediately after each
# boundary's closing punctuation. The PRD specifies markers go
# "immediately after the closing punctuation of the cited sentence,"
# so a sentence text "Foo.{{cit_001}} Bar." carries cit_001 with the
# `Foo.` sentence, not with `Bar.`.
_SENTENCE_END_RE = re.compile(r"[.?!](?:\{\{cit_\d+\}\})*(?=\s+|$)")

# Common abbreviations that shouldn't terminate a sentence — keeps the
# "27%" sentence from splitting at "i.e." or "etc.".
_ABBREVIATIONS = (
    "e.g.", "i.e.", "etc.", "vs.", "Mr.", "Mrs.", "Ms.", "Dr.",
    "Inc.", "Co.", "Ltd.", "U.S.", "U.K.", "U.S.A.",
)


def _split_sentences(body: str) -> list[str]:
    """Split a body into sentences while preserving any `{{cit_N}}`
    markers attached to each sentence's terminator. Returns a list of
    sentence strings; each retains the markers attached to its own
    closing punctuation (so `_sentence_has_marker` correctly assigns
    citation to the cited sentence rather than the following one).

    Markdown structures (lists, tables) are kept inline — each list
    item or table row is treated as one sentence for citable-claim
    purposes.
    """
    if not body:
        return []
    # Replace abbreviation periods with a sentinel before splitting,
    # then restore. This avoids over-splitting on "e.g." etc.
    sentinel = "\x00DOT\x00"
    masked = body
    for abbr in _ABBREVIATIONS:
        masked = masked.replace(abbr, abbr.replace(".", sentinel))

    sentences: list[str] = []
    last_end = 0
    for match in _SENTENCE_END_RE.finditer(masked):
        sentence_text = masked[last_end:match.end()].strip()
        if sentence_text:
            sentences.append(sentence_text.replace(sentinel, "."))
        last_end = match.end()
    if last_end < len(masked):
        tail = masked[last_end:].strip()
        if tail:
            sentences.append(tail.replace(sentinel, "."))
    return sentences


# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------

# C1 — Percentage / percent / pct / percentage points.
_C1_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:%|percent\b|pct\b|percentage\s+points\b)",
    re.IGNORECASE,
)

# C2 — Numeral with currency. Handles `$100M`, `$1,000`, `1.2 billion USD`,
# `€50`, `£20`, `1.5 trillion EUR`.
_C2_RE = re.compile(
    r"(?:[$€£¥]\s*\d[\d,.]*(?:\s*(?:million|billion|trillion|m|bn|k))?"
    r"|\b\d[\d,.]*\s*(?:million|billion|trillion)\s+(?:USD|EUR|GBP|JPY)\b"
    r"|\b\d[\d,.]*\s+(?:USD|EUR|GBP|JPY)\b)",
    re.IGNORECASE,
)

# C3 — Four-digit year 1990–2099 used as a date. Requires the year be
# preceded by a date-context word so we don't false-positive on bare
# numbers ("Model 2024X", "Order number 2024 in queue"). The bare-year
# arm was tried in early Phase 4 but produced too many false positives;
# requiring a context word trades some recall for high precision.
_C3_RE = re.compile(
    r"\b(?:in|since|during|by|as\s+of|through|until|before|after|"
    r"between|throughout|until|after|prior\s+to|circa|c\.)\s+"
    r"(?:19[9]\d|20\d{2})(?:'s|s)?\b",
    re.IGNORECASE,
)

# C4 — `according to <ProperNoun>` / `<ProperNoun> reports/found/survey`.
# The proper-noun arm requires capitalized initial char. Inline
# `(?i:according\s+to\s+)` lowercases the lead phrase so "According" /
# "according" both match without lowercasing the proper-noun arm.
_C4_RE = re.compile(
    r"(?i:\baccording\s+to\s+)[A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,3}\b"
    r"|\b[A-Z][\w&.-]+(?:\s+[A-Z][\w&.-]+){0,3}\s+(?:reports?|found|survey(?:ed)?|study|studied|study\s+found)\b",
)

# C5 — `studies show` / `research shows` / `data shows` / `analysts predict`.
_C5_RE = re.compile(
    r"\b(?:studies?|research|data|analysts?|surveys?|polls?|reports?)\s+"
    r"(?:show(?:s|ed)?|indicate(?:s|d)?|suggest(?:s|ed)?|predict(?:s|ed)?|"
    r"reveal(?:s|ed)?|find(?:s|ings)?|claim(?:s|ed)?)\b",
    re.IGNORECASE,
)

# C7 — Duration-as-recommendation (NEW in Phase 4).
# Catches forms like:
#   `a 4-to-6 week refresh cadence`
#   `a 60-day affiliate audit window`
#   `a 90-minute review cycle`
#   `a 2-week sprint cooldown`
#
# Phase 4 review fix #1: the range arm `4-to-6` failed under the original
# `(?:to|-|–|—)` alternation because the structure `<hyphen><to><hyphen>`
# can't be matched as a single token. Rewriting as `[\s-]*(?:to|–|—)?[\s-]*`
# accepts `4-to-6` / `4-6` / `4 to 6` uniformly. The regex also now:
#   - Consumes optional leading article (`a`/`an`/`the`) so soften can
#     replace the phrase including the article — no more `"a a typical"`
#     duplication.
#   - Consumes trailing recommendation noun phrases — `refresh cadence`
#     matches as a unit instead of leaving `cadence` orphaned after
#     soften.
_C7_NOUNS = (
    r"cadence|window|cycle|interval|period|review|audit|"
    r"refresh|sprint|cooldown|cool-down|cool\s+down|lookback|"
    r"horizon|warranty|grace\s+period|onboarding"
)
_C7_RE = re.compile(
    r"(?:\b(?:a|an|the)\s+)?"                  # optional leading article
    r"\b\d+(?:[\s-]*(?:to|–|—)?[\s-]*\d+)?"    # numeric duration / range
    r"[\s-]+"                                  # space or hyphen before unit
    r"(?:second|minute|hour|day|week|month|year)s?\b"
    r"(?:[\s-]+\w+){0,3}?[\s-]+"               # up to 3 modifier words
    r"(?:" + _C7_NOUNS + r")"                  # primary recommendation noun
    r"(?:[\s-]+(?:" + _C7_NOUNS + r"))*"       # optional chained nouns
    r"\b",
    re.IGNORECASE,
)

# C8 — Frequency-as-recommendation (NEW).
# Phase 4 review fix #1: optional leading article so soften can replace
# the article-bearing phrase ("a weekly review") without doubling it.
_C8_RE = re.compile(
    r"\b(?:every|each)\s+\d+\s+(?:hours?|days?|weeks?|months?|quarters?|years?)\b"
    r"|(?:\b(?:a|an|the)\s+)?"
    r"\b(?:hourly|daily|weekly|biweekly|bi-weekly|monthly|"
    r"quarterly|semiannually|semi-annually|annually|yearly)\s+"
    r"(?:audit|review|refresh|check|update|inspection|sync|"
    r"reconciliation|cleanup|standup|stand-up)\b",
    re.IGNORECASE,
)

# C9 — Operational-percentage-as-recommendation (NEW).
_C9_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s+(?:rule|threshold|target|cap|floor|ceiling|"
    r"minimum|maximum|baseline|benchmark|cutoff|cut-off)\b"
    r"|\baim\s+for\s+\d+(?:\.\d+)?%"
    r"|\bkeep\s+(?:it\s+|under\s+|below\s+|above\s+)?\d+(?:\.\d+)?%",
    re.IGNORECASE,
)


# Pattern registry: (pattern_id, regex). C6 lives outside this list
# because it requires the SIE entity list as input.
_PATTERN_REGISTRY: tuple[tuple[str, re.Pattern], ...] = (
    ("C1", _C1_RE),
    ("C2", _C2_RE),
    ("C3", _C3_RE),
    ("C4", _C4_RE),
    ("C5", _C5_RE),
    ("C7", _C7_RE),
    ("C8", _C8_RE),
    ("C9", _C9_RE),
)


# C7-C9 are operational claims eligible for auto-soften when the LLM
# retry can't produce a citation. C1-C6 are NOT softened — they're
# statistics/years/source-attributed facts where softening would
# introduce more harm than it fixes.
_OPERATIONAL_CLAIM_PATTERN_IDS = frozenset({"C7", "C8", "C9"})


# ---------------------------------------------------------------------------
# Auto-soften lookup
# ---------------------------------------------------------------------------
#
# Each entry is a (regex, soften_fn) pair. The soften_fn receives the
# regex match object and returns the replacement string. Entries are
# tried in order; the first match that yields a different string is
# applied. Entries are intentionally small in v1 — extend as production
# data shows which patterns recur.

@dataclass
class _SoftenRule:
    pattern: re.Pattern
    fn: callable
    description: str


_C7_NOUN_PHRASE_RE = re.compile(
    r"((?:" + _C7_NOUNS + r")"
    r"(?:[\s-]+(?:" + _C7_NOUNS + r"))*)"
    r"\s*$",
    re.IGNORECASE,
)


def _soften_duration_window(match: re.Match) -> str:
    """Phase 4 review fix #1: replace the entire matched phrase
    (including any leading article) with `a typical <noun phrase>` so
    no fragments of the original duration remain orphaned in the body.

    Examples:
      "a 4-to-6 week refresh cadence" → "a typical refresh cadence"
      "a 60-day affiliate audit window" → "a typical audit window"
      "a 2-week sprint cooldown" → "a typical sprint cooldown"

    The original strategy of appending a parenthetical scale phrase
    (e.g. "(every few weeks)") was dropped because (a) day-scale
    durations like "60-day window" combined awkwardly with scale
    phrases ("(a brief window)" produced "audit window (a brief
    window)"), and (b) the scale phrase often misrepresented the
    original duration after soften. Pure noun-only phrasing reads
    cleanly and stays factually neutral.
    """
    text = match.group(0)
    noun_match = _C7_NOUN_PHRASE_RE.search(text)
    if noun_match:
        noun_phrase = noun_match.group(1).strip()
        # Lower-case the noun phrase but preserve any internal hyphenation.
        noun_phrase = re.sub(r"\s+", " ", noun_phrase.lower())
        return f"a typical {noun_phrase}"
    return "a typical pattern"


_C8_ACTION_NOUNS_RE = re.compile(
    r"(audit|review|refresh|check|update|inspection|sync|"
    r"reconciliation|cleanup|standup|stand-up)\s*$",
    re.IGNORECASE,
)


def _soften_frequency(match: re.Match) -> str:
    """Phase 4 review fix #1: pure article+noun output for `weekly
    review` / `monthly audit` style; pure phrase output for `every N
    units` style. No mid-replacement fragments left orphaned in the
    body.

    Examples:
      "a weekly review" → "a regular review"
      "weekly audit" → "a regular audit"
      "every 4 weeks" → "on a regular schedule"
    """
    text = match.group(0)
    noun_match = _C8_ACTION_NOUNS_RE.search(text)
    if noun_match:
        return f"a regular {noun_match.group(1).lower()}"
    # `every <N> <unit>` form has no trailing action noun.
    return "on a regular schedule"


def _soften_operational_percentage(match: re.Match) -> str:
    """`5% rule` → `a small percentage rule`. `aim for 30%` →
    `aim for a moderate share`. `20% threshold` → `a moderate threshold`."""
    text = match.group(0)
    lower = text.lower()
    pct_match = re.match(r"\s*(\d+(?:\.\d+)?)%", text)
    if pct_match:
        pct = float(pct_match.group(1))
        if pct < 10:
            qualifier = "a small"
        elif pct < 30:
            qualifier = "a modest"
        elif pct < 60:
            qualifier = "a moderate"
        else:
            qualifier = "a substantial"
    else:
        qualifier = "a moderate"
    if "rule" in lower:
        return f"{qualifier} percentage rule"
    if "threshold" in lower:
        return f"{qualifier} threshold"
    if "target" in lower:
        return f"{qualifier} target"
    if "cap" in lower:
        return f"{qualifier} cap"
    if "floor" in lower:
        return f"{qualifier} floor"
    if "ceiling" in lower:
        return f"{qualifier} ceiling"
    if "aim for" in lower:
        return f"aim for {qualifier} share"
    if "keep" in lower:
        return f"keep within {qualifier} bounds"
    return f"{qualifier} share"


_SOFTEN_RULES: tuple[_SoftenRule, ...] = (
    _SoftenRule(
        pattern=_C7_RE, fn=_soften_duration_window,
        description="duration-as-recommendation",
    ),
    _SoftenRule(
        pattern=_C8_RE, fn=_soften_frequency,
        description="frequency-as-recommendation",
    ),
    _SoftenRule(
        pattern=_C9_RE, fn=_soften_operational_percentage,
        description="operational-percentage",
    ),
)


# ---------------------------------------------------------------------------
# Detection + coverage
# ---------------------------------------------------------------------------


@dataclass
class ClaimMatch:
    """A single citable-claim sentence in a section body."""

    sentence: str
    pattern_ids: list[str] = field(default_factory=list)
    has_citation_marker: bool = False
    is_operational: bool = False  # any pattern_id is in C7-C9


@dataclass
class SectionCoverage:
    """Coverage analysis for one section body."""

    citable_claims: int = 0
    cited_claims: int = 0
    matches: list[ClaimMatch] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.citable_claims == 0:
            return 1.0
        return self.cited_claims / self.citable_claims


def _sentence_has_marker(sentence: str) -> bool:
    return bool(_MARKER_RE.search(sentence))


def _entity_pattern(entities: Iterable[str]) -> Optional[re.Pattern]:
    """Build the C6 entity matcher from the SIE entity list. Returns
    None when the list is empty (C6 doesn't fire)."""
    cleaned = [
        re.escape(e.strip()) for e in entities
        if isinstance(e, str) and e.strip() and len(e.strip()) > 1
    ]
    if not cleaned:
        return None
    return re.compile(r"\b(?:" + "|".join(cleaned) + r")\b", re.IGNORECASE)


def detect_citable_claims(
    body: str,
    *,
    entities: Iterable[str] = (),
) -> list[ClaimMatch]:
    """Detect citable-claim sentences in `body`. Each sentence
    containing one or more pattern matches is one ClaimMatch.

    `entities` is the SIE Required-term entity list (`is_entity == True`
    only) — used by C6 to detect "entity name + quantitative qualifier"
    sentences. Pass an empty list to skip C6.
    """
    if not body:
        return []
    entity_re = _entity_pattern(entities)
    matches: list[ClaimMatch] = []
    for sentence in _split_sentences(body):
        ids: list[str] = []
        for pid, regex in _PATTERN_REGISTRY:
            if regex.search(sentence):
                ids.append(pid)
        # C6 requires entity AND a quantitative/temporal qualifier (C1-C3).
        if entity_re is not None and entity_re.search(sentence):
            if any(p in {"C1", "C2", "C3"} for p in ids):
                ids.append("C6")
        if not ids:
            continue
        matches.append(ClaimMatch(
            sentence=sentence,
            pattern_ids=ids,
            has_citation_marker=_sentence_has_marker(sentence),
            is_operational=any(p in _OPERATIONAL_CLAIM_PATTERN_IDS for p in ids),
        ))
    return matches


def coverage_for_body(
    body: str,
    *,
    entities: Iterable[str] = (),
) -> SectionCoverage:
    """Run detection + count citable + cited."""
    matches = detect_citable_claims(body, entities=entities)
    citable = len(matches)
    cited = sum(1 for m in matches if m.has_citation_marker)
    return SectionCoverage(
        citable_claims=citable,
        cited_claims=cited,
        matches=matches,
    )


# ---------------------------------------------------------------------------
# Retry directive + auto-soften
# ---------------------------------------------------------------------------


def coverage_retry_directive(
    coverage: SectionCoverage,
    available_citation_ids: list[str],
    *,
    threshold: float = 0.5,
) -> str:
    """Build a `COVERAGE_RETRY:` directive listing uncited citable
    claims and asking the LLM to either add a marker (from the supplied
    pool) or rewrite the sentence to remove the specific claim."""
    uncited = [m for m in coverage.matches if not m.has_citation_marker]
    if not uncited:
        return ""
    listed = "\n".join(
        f"  - {m.sentence}  (matched: {','.join(m.pattern_ids)})"
        for m in uncited[:10]  # cap to keep prompt size bounded
    )
    pool = (
        ", ".join(sorted(available_citation_ids))
        if available_citation_ids else "NONE — rewrite to remove the claim"
    )
    return (
        f"Coverage of citable claims is below {int(threshold * 100)}% "
        f"({coverage.cited_claims}/{coverage.citable_claims}). "
        f"For each uncited claim listed below, EITHER add a {{{{cit_N}}}} "
        f"marker from the available pool [{pool}] immediately after the "
        f"sentence's closing punctuation, OR rewrite the sentence to "
        f"remove the specific statistic/year/duration so no marker is "
        f"needed. Operational durations and frequencies (C7/C8) — like "
        f"'4-to-6 week refresh cadence' — should be SOFTENED if no "
        f"citation supports them; do not invent sources.\n\n"
        f"Uncited sentences:\n{listed}"
    )


@dataclass
class SoftenReplacement:
    original: str
    softened: str
    rule: str  # description of the soften rule that fired


_PLACEHOLDER_FMT = "\x00CITED_{idx}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00CITED_(\d+)\x00")


def _find_cited_sentence_spans(body: str) -> list[tuple[int, int]]:
    """Phase 4 review fix #2 — locate every cited sentence's character
    span [start, end] in `body`. A "cited sentence" ends in `.?!`
    immediately followed by a `{{cit_N}}` marker; the span runs from
    the previous sentence boundary (or start of body) through the end
    of the marker.

    The walk-back for the previous sentence boundary is bounded by the
    end of the PREVIOUS cited span (`last_end`) — without this bound,
    a body containing `"Foo.{{cit_1}} Bar.{{cit_2}}"` would compute
    Bar's span starting at position-after-Foo's-period (i.e. inside
    Foo's marker), causing restoration to scramble both spans.

    Used by `apply_soften` to mask cited regions before running the
    soften rules so already-cited operational claims keep their
    precise wording — the citation marker grounds the precise text,
    not a hedged version of it.
    """
    spans: list[tuple[int, int]] = []
    last_end = 0
    for marker in _MARKER_RE.finditer(body):
        marker_start = marker.start()
        marker_end = marker.end()
        if marker_start == 0 or body[marker_start - 1] not in ".?!":
            # Marker not attached to a sentence terminator — malformed,
            # leave the surrounding region open to soften.
            continue
        # Walk backward from the terminator to find the previous
        # sentence boundary, bounded by the end of the previous cited
        # span so we don't reach back into already-assigned regions.
        terminator_pos = marker_start - 1
        boundary = last_end
        for i in range(terminator_pos - 1, last_end - 1, -1):
            if body[i] in ".?!":
                boundary = i + 1
                break
        # Skip leading whitespace inside the cited region so the span
        # tracks the actual sentence text, not surrounding indentation.
        while boundary < terminator_pos and body[boundary].isspace():
            boundary += 1
        spans.append((boundary, marker_end))
        last_end = marker_end
    return spans


def apply_soften(body: str) -> tuple[str, list[SoftenReplacement]]:
    """Run all soften rules over `body`. Returns the (possibly mutated)
    body plus a list of replacements that fired.

    Rules apply iteratively in registry order. Each rule's regex
    finds non-overlapping matches; we replace ALL matches per rule
    before moving to the next rule.

    Phase 4 review fix #2: sentences with `{{cit_N}}` markers are
    EXCLUDED from soften — the citation grounds the precise claim, so
    softening would leave the marker pointing at hedged text. We mask
    cited regions with stable placeholders before running soften, then
    restore them. The placeholders contain control characters that no
    soften regex matches.
    """
    if not body:
        return body, []
    cited_spans = _find_cited_sentence_spans(body)
    cited_texts: list[str] = [body[s:e] for s, e in cited_spans]
    masked = body
    # Replace cited spans in REVERSE order so character positions
    # earlier in the body remain valid through each substitution.
    for idx in reversed(range(len(cited_spans))):
        s, e = cited_spans[idx]
        masked = masked[:s] + _PLACEHOLDER_FMT.format(idx=idx) + masked[e:]

    out = masked
    replacements: list[SoftenReplacement] = []
    for rule in _SOFTEN_RULES:
        def _sub(m: re.Match, _rule: _SoftenRule = rule) -> str:
            try:
                soft = _rule.fn(m)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "writer.soften.rule_failed",
                    extra={"rule": _rule.description, "error": str(exc)},
                )
                return m.group(0)
            if soft != m.group(0):
                replacements.append(SoftenReplacement(
                    original=m.group(0),
                    softened=soft,
                    rule=_rule.description,
                ))
            return soft
        out = rule.pattern.sub(_sub, out)

    # Restore cited regions.
    if cited_texts:
        def _restore(m: re.Match) -> str:
            idx = int(m.group(1))
            if 0 <= idx < len(cited_texts):
                return cited_texts[idx]
            return m.group(0)
        out = _PLACEHOLDER_RE.sub(_restore, out)
    return out, replacements
