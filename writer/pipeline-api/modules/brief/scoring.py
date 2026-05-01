"""Step 4 + 5 — Aggregation, semantic scoring, and heading polish."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from models.brief import HeadingSource

from .llm import claude_json, cosine, embed_batch
from .parsers import levenshtein_ratio, normalize_text

logger = logging.getLogger(__name__)

LLM_FANOUT_SOURCES = {
    "llm_fanout_chatgpt",
    "llm_fanout_claude",
    "llm_fanout_gemini",
    "llm_fanout_perplexity",
}
LLM_RESPONSE_SOURCES = {
    "llm_response_chatgpt",
    "llm_response_claude",
    "llm_response_gemini",
    "llm_response_perplexity",
}


@dataclass
class HeadingCandidate:
    text: str
    source: HeadingSource
    original_source: Optional[str] = None
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    semantic_score: float = 0.0
    heading_priority: float = 0.0
    embedding: list[float] = field(default_factory=list)
    discard_reason: Optional[str] = None
    exempt: bool = False


def aggregate_candidates(
    serp_stats: dict[str, dict],
    paa_questions: list[str],
    autocomplete: list[str],
    keyword_suggestions: list[str],
    llm_fanout_by_source: dict[str, list[str]],
    llm_response_by_source: dict[str, list[str]],
) -> list[HeadingCandidate]:
    """Step 4 — combine all sources, dedup with Levenshtein 0.15.

    Tracks `llm_fanout_consensus` (count of distinct LLMs that surfaced a
    near-duplicate text). Pure SERP/autocomplete/keyword_suggestion entries
    get `llm_fanout_consensus: 0`.
    """
    raw: list[HeadingCandidate] = []

    for norm, stats in serp_stats.items():
        raw.append(HeadingCandidate(
            text=stats["representative_text"],
            source="serp",
            serp_frequency=stats["serp_frequency"],
            avg_serp_position=stats.get("avg_serp_position"),
        ))

    for q in paa_questions:
        raw.append(HeadingCandidate(text=q, source="paa"))

    for q in autocomplete:
        raw.append(HeadingCandidate(text=q, source="autocomplete"))

    for q in keyword_suggestions:
        raw.append(HeadingCandidate(text=q, source="keyword_suggestion"))

    for src, queries in llm_fanout_by_source.items():
        for q in queries:
            raw.append(HeadingCandidate(text=q, source=src))

    for src, items in llm_response_by_source.items():
        for s in items:
            raw.append(HeadingCandidate(text=s, source=src))

    # Fuzzy dedup with consensus tracking
    deduped: list[HeadingCandidate] = []
    norm_index: list[str] = []

    for c in raw:
        norm = normalize_text(c.text)
        if not norm:
            continue
        merged = False
        for i, existing_norm in enumerate(norm_index):
            if levenshtein_ratio(norm, existing_norm) <= 0.15:
                existing = deduped[i]
                # Merge: prefer the one with stronger signal
                if c.serp_frequency > existing.serp_frequency:
                    existing.text = c.text
                    existing.source = c.source
                    existing.serp_frequency = c.serp_frequency
                    existing.avg_serp_position = c.avg_serp_position
                # Track LLM consensus
                _add_consensus(existing, c.source)
                merged = True
                break
        if not merged:
            _add_consensus(c, c.source)
            deduped.append(c)
            norm_index.append(norm)

    return deduped


def _add_consensus(candidate: HeadingCandidate, source: str) -> None:
    """If source is one of the LLM sources, bump the consensus count.

    We track distinct LLMs (max 4) by stashing per-LLM markers on the candidate.
    """
    llm_key = None
    for prefix in ("llm_fanout_", "llm_response_"):
        if source.startswith(prefix):
            llm_key = source.replace(prefix, "")
            break
    if not llm_key:
        return

    seen = getattr(candidate, "_llm_seen", None)
    if seen is None:
        seen = set()
        candidate._llm_seen = seen  # type: ignore[attr-defined]
    if llm_key not in seen:
        seen.add(llm_key)
        candidate.llm_fanout_consensus = len(seen)


async def score_candidates(
    keyword: str,
    candidates: list[HeadingCandidate],
    semantic_threshold: float = 0.55,
) -> tuple[list[HeadingCandidate], list[HeadingCandidate], list[float]]:
    """Step 5 — embed everything, compute semantic scores, filter below threshold.

    Returns (kept, discarded_low_score, keyword_embedding).
    """
    if not candidates:
        return ([], [], [])

    texts = [keyword] + [c.text for c in candidates]
    vectors = await embed_batch(texts)
    if not vectors:
        return (candidates, [], [])

    keyword_vec = vectors[0]
    for c, vec in zip(candidates, vectors[1:]):
        c.embedding = vec
        c.semantic_score = cosine(keyword_vec, vec)

    kept: list[HeadingCandidate] = []
    discarded: list[HeadingCandidate] = []
    for c in candidates:
        if c.semantic_score >= semantic_threshold:
            kept.append(c)
        else:
            c.discard_reason = "below_semantic_threshold"
            discarded.append(c)

    # Failure-mode: <3 above threshold → lower to 0.40 and retry filter
    if len(kept) < 3:
        kept = []
        discarded = []
        for c in candidates:
            if c.semantic_score >= 0.40:
                c.discard_reason = None
                kept.append(c)
            else:
                c.discard_reason = "below_semantic_threshold"
                discarded.append(c)

    return (kept, discarded, keyword_vec)


def compute_priority(candidates: list[HeadingCandidate]) -> None:
    """Step 5 — heading_priority = 0.4*semantic + 0.25*serp_freq_norm
    + 0.15*position_weight + 0.2*llm_consensus_norm.
    """
    for c in candidates:
        norm_freq = min((c.serp_frequency or 0) / 20, 1.0)
        if c.avg_serp_position:
            position_weight = max(1.0 - ((c.avg_serp_position - 1) / 20), 0.0)
        else:
            position_weight = 0.0
        norm_consensus = (c.llm_fanout_consensus or 0) / 4
        c.heading_priority = (
            0.4 * c.semantic_score
            + 0.25 * norm_freq
            + 0.15 * position_weight
            + 0.2 * norm_consensus
        )


async def polish_headings(candidates: list[HeadingCandidate]) -> None:
    """Step 5 — LLM polish for awkward, keyword-stuffed, or raw query-format
    candidates (autocomplete, fan-out, etc.). Updates text in place and
    sets source='synthesized' with original_source preserved.

    Single batched LLM call; on failure leaves headings unchanged.
    """
    needs_polish: list[int] = []
    for i, c in enumerate(candidates):
        if c.source in ("autocomplete", "keyword_suggestion") or c.source in LLM_FANOUT_SOURCES:
            needs_polish.append(i)
    if not needs_polish:
        return

    items = [{"i": i, "text": candidates[i].text} for i in needs_polish]
    system = (
        "You rewrite raw search-query text into clean, professional H2 heading "
        "phrasing for an SEO blog article. Keep the original meaning. Avoid "
        "stuffing the keyword. Use sentence case. No trailing punctuation. "
        "Respond with a JSON array of objects: [{i, text}]."
    )
    user = (
        "Rewrite each candidate as a clean H2 heading. Preserve meaning.\n"
        f"Candidates:\n{items}"
    )
    try:
        polished = await claude_json(system, user, max_tokens=2000, temperature=0.2)
        if isinstance(polished, list):
            for entry in polished:
                idx = entry.get("i")
                new_text = entry.get("text")
                if isinstance(idx, int) and 0 <= idx < len(candidates) and new_text:
                    c = candidates[idx]
                    c.original_source = c.source
                    c.text = new_text.strip()
                    c.source = "synthesized"
    except Exception as exc:
        logger.warning("heading polish failed, leaving raw: %s", exc)
