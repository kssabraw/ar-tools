"""Step 4 - Subtopic Aggregation (Brief Generator v2.0).

Implements PRD §5 Step 4. Combines every candidate source into a unified
list of v2 `Candidate` objects (defined in graph.py) with:

  - serp_frequency        from SERP stats
  - avg_serp_position     from SERP stats (None for non-SERP sources)
  - source_urls           preserved from SERP entries
  - llm_fanout_consensus  count of distinct LLMs that surfaced a near-dup

Sources combined (PRD §5 Step 4):
  - SERP stats (already-aggregated in parsers.aggregate_serp_stats)
  - PAA questions
  - Autocomplete queries
  - Keyword suggestions
  - LLM fan-out queries (4 LLMs)
  - LLM response extractions (4 LLMs)
  - Persona gap questions (added in second pass - PRD §5 Step 4 ordering note)

Dedup uses Levenshtein ratio ≤ 0.15 (matching the v1.7 threshold) so
near-paraphrases collapse into a single candidate. The first occurrence
wins on text + source attribution; SERP signal beats LLM signal when
merging since SERP frequency is strictly more authoritative.

This module is the v2.0 replacement for `scoring.aggregate_candidates`.
The output type is the v2 `Candidate` from graph.py - not the v1.8
HeadingCandidate.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.brief import HeadingSource

from .graph import Candidate
from .parsers import levenshtein_ratio, normalize_text
from .sanitization import sanitize_heading

logger = logging.getLogger(__name__)


# LLM source prefix → LLM identifier. Used to count distinct LLMs in
# `llm_fanout_consensus`. fan-out and response from the same LLM count once.
_LLM_PREFIXES = ("llm_fanout_", "llm_response_")

# Levenshtein ratio threshold for fuzzy dedup (PRD §5 Step 4 - unchanged).
LEVENSHTEIN_DEDUP_THRESHOLD = 0.15


def _llm_key(source: str) -> Optional[str]:
    """Extract the LLM identifier from a source string, if any.

    Returns "chatgpt" / "claude" / "gemini" / "perplexity" for either the
    fan-out or response variant of that source. Returns None for non-LLM
    sources.
    """
    for prefix in _LLM_PREFIXES:
        if source.startswith(prefix):
            return source[len(prefix):]
    return None


def _bump_consensus(cand: Candidate, source: str) -> None:
    """Increment llm_fanout_consensus when source is an LLM not yet seen.

    Stashes a `_llm_seen` set on the candidate so we count distinct LLMs
    and not raw fan-out + response duplication. Stays at 0 for non-LLM
    sources.
    """
    key = _llm_key(source)
    if not key:
        return
    seen: set[str] = getattr(cand, "_llm_seen", None) or set()
    if key not in seen:
        seen.add(key)
        cand.llm_fanout_consensus = len(seen)
        # Use object.__setattr__ in case Candidate is later frozen
        cand._llm_seen = seen  # type: ignore[attr-defined]


def aggregate_candidates(
    *,
    serp_stats: dict[str, dict],
    paa_questions: list[str],
    autocomplete: list[str],
    keyword_suggestions: list[str],
    llm_fanout_by_source: dict[str, list[str]],
    llm_response_by_source: dict[str, list[str]],
    persona_gap_questions: Optional[list[str]] = None,
) -> list[Candidate]:
    """Step 4 aggregation: produce v2 Candidate objects from every source.

    Pre-conditions:
      - `serp_stats` is the output of parsers.aggregate_serp_stats; each
        value carries `representative_text`, `serp_frequency`,
        `avg_serp_position`, and `source_urls`.
      - All non-SERP source lists are raw strings (pre-sanitization).

    Sanitization (CQ PRD R2) is applied at intake to non-SERP entries.
    SERP entries were sanitized in parse_serp; their representative_text
    is used as-is.

    Levenshtein dedup uses `LEVENSHTEIN_DEDUP_THRESHOLD = 0.15`. When a
    new candidate matches an existing one:
      - existing keeps its identity (text, source) but
        absorbs URL evidence
      - if the new entry has higher serp_frequency, the existing record
        is upgraded (text + source + frequency + position)
      - LLM consensus is bumped if the merging source is an LLM not yet
        recorded on the existing candidate

    Persona gap questions (when supplied) are appended at the end so the
    same dedup logic merges them with anything similar that already came
    from SERP / Reddit / fan-out (PRD §5 Step 4 ordering note).
    """
    raw: list[Candidate] = []

    # SERP candidates first - they bring serp_frequency and avg_serp_position.
    for stats in serp_stats.values():
        text = stats.get("representative_text") or ""
        if not text:
            continue
        cand = Candidate(
            text=text,
            source="serp",
            serp_frequency=int(stats.get("serp_frequency") or 0),
            avg_serp_position=stats.get("avg_serp_position"),
            source_urls=list(stats.get("source_urls") or []),
            raw_text=stats.get("raw_text"),
        )
        raw.append(cand)

    def _push(text: str, source: HeadingSource) -> None:
        cleaned = sanitize_heading(text, source_url=None)
        if cleaned is None:
            return
        raw.append(Candidate(text=cleaned, source=source, raw_text=text))

    for q in paa_questions:
        _push(q, "paa")

    for q in autocomplete:
        _push(q, "autocomplete")

    for q in keyword_suggestions:
        _push(q, "keyword_suggestion")

    for src, queries in llm_fanout_by_source.items():
        for q in queries:
            _push(q, src)  # type: ignore[arg-type]

    for src, items in llm_response_by_source.items():
        for s in items:
            _push(s, src)  # type: ignore[arg-type]

    if persona_gap_questions:
        for q in persona_gap_questions:
            _push(q, "persona_gap")

    # ---- fuzzy dedup with consensus tracking ----
    deduped: list[Candidate] = []
    norm_index: list[str] = []

    for c in raw:
        norm = normalize_text(c.text)
        if not norm:
            continue
        merged = False
        for i, existing_norm in enumerate(norm_index):
            if levenshtein_ratio(norm, existing_norm) <= LEVENSHTEIN_DEDUP_THRESHOLD:
                existing = deduped[i]
                # Stronger SERP signal wins on identity (text + source);
                # weaker entries still contribute their LLM consensus + URLs.
                if c.serp_frequency > existing.serp_frequency:
                    existing.text = c.text
                    existing.source = c.source
                    existing.serp_frequency = c.serp_frequency
                    existing.avg_serp_position = c.avg_serp_position
                # Union URL set so silos / debugging can trace provenance
                for u in c.source_urls:
                    if u not in existing.source_urls:
                        existing.source_urls.append(u)
                _bump_consensus(existing, c.source)
                merged = True
                break
        if not merged:
            _bump_consensus(c, c.source)
            deduped.append(c)
            norm_index.append(norm)

    logger.info(
        "brief.aggregation.complete",
        extra={
            "input_count": len(raw),
            "deduped_count": len(deduped),
            "serp_seed_count": len(serp_stats),
            "persona_gap_count": len(persona_gap_questions or []),
        },
    )

    return deduped
