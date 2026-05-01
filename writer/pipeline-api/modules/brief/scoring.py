"""Step 4 + 5 — Aggregation, semantic scoring, and heading polish.

v1.8 (CQ PRD v1.0 R1, R2):
- aggregate_candidates() applies sanitization at intake (R2) and threads
  source URLs through the candidate so cluster_evidence can show provenance.
- HeadingCandidate gains cluster fields (cluster_id, is_canonical,
  cluster_variants) populated by clustering.cluster_candidates +
  clustering.pick_canonicals.
- polish_headings() operates on canonicals only — see polish_canonicals().
- compute_priority() unchanged in formula; clustering rolls up SERP /
  consensus signals onto canonicals before this is recomputed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from models.brief import HeadingSource

from .llm import claude_json, cosine, embed_batch
from .parsers import levenshtein_ratio, normalize_text
from .sanitization import sanitize_heading

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
class ClusterVariant:
    """A non-canonical member of a heading cluster.

    Stored on the canonical's `cluster_variants` list so downstream
    consumers can see what got merged. Mirrors models.brief.HeadingClusterEvidence
    for serialization.
    """
    text: str
    source: HeadingSource
    source_url: Optional[str]
    source_urls: list[str]
    avg_serp_position: Optional[float]
    cosine_to_canonical: float
    heading_priority: float


@dataclass
class HeadingCandidate:
    text: str
    source: HeadingSource
    raw_text: Optional[str] = None  # pre-sanitization (R2)
    original_source: Optional[str] = None
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    source_urls: list[str] = field(default_factory=list)
    llm_fanout_consensus: int = 0
    semantic_score: float = 0.0
    heading_priority: float = 0.0
    embedding: list[float] = field(default_factory=list)
    discard_reason: Optional[str] = None
    exempt: bool = False
    # CQ PRD v1.0 R1 — cluster fields
    cluster_id: int = -1
    is_canonical: bool = False
    cluster_variants: list[ClusterVariant] = field(default_factory=list)
    semantic_duplicate_of_cluster: Optional[int] = None


def aggregate_candidates(
    serp_stats: dict[str, dict],
    paa_questions: list[str],
    autocomplete: list[str],
    keyword_suggestions: list[str],
    llm_fanout_by_source: dict[str, list[str]],
    llm_response_by_source: dict[str, list[str]],
) -> list[HeadingCandidate]:
    """Step 4 — combine all sources, sanitize, dedup with Levenshtein 0.15.

    Sanitization (CQ PRD R2) runs at intake on all non-SERP sources here
    (SERP gets sanitized earlier in parse_serp). Tracks `llm_fanout_consensus`
    (count of distinct LLMs that surfaced a near-duplicate text). Pure
    SERP/autocomplete/keyword_suggestion entries get `llm_fanout_consensus: 0`.
    """
    raw: list[HeadingCandidate] = []

    for stats in serp_stats.values():
        raw.append(HeadingCandidate(
            text=stats["representative_text"],
            raw_text=stats.get("raw_text"),
            source="serp",
            serp_frequency=stats["serp_frequency"],
            avg_serp_position=stats.get("avg_serp_position"),
            source_urls=list(stats.get("source_urls") or []),
        ))

    def _push(text: str, source: HeadingSource) -> None:
        cleaned = sanitize_heading(text, source_url=None)
        if cleaned is None:
            return
        raw.append(HeadingCandidate(text=cleaned, raw_text=text, source=source))

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
                # Union the URL set so cluster_evidence can show all sources
                for u in c.source_urls:
                    if u not in existing.source_urls:
                        existing.source_urls.append(u)
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

    After clustering rolls up cluster-level SERP/consensus signals onto
    canonicals (clustering._rollup_cluster_signals), the caller should
    re-run this so canonicals get a priority that reflects the full cluster.
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

    v1.8: when called after clustering, the caller passes ONLY canonicals
    so we don't waste polish budget rewriting paraphrases that have already
    been merged. This function itself is unchanged — it just receives a
    smaller pool.

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


async def arbitrate_soft_pairs(
    candidates: list[HeadingCandidate],
    soft_pairs: list,  # list[clustering.SoftPair] — typed loosely to avoid circular import
) -> set[tuple[int, int]]:
    """Optional second pass: ask the LLM to confirm which soft-cluster pairs
    are actually paraphrases of the same idea.

    Returns the set of (a_index, b_index) pairs the LLM confirmed should
    be merged. Caller is responsible for unioning them into clusters.
    Cheap (one LLM call); fails open (returns empty set, leaving pairs split).
    """
    if not soft_pairs:
        return set()

    items = []
    for k, p in enumerate(soft_pairs):
        items.append({
            "k": k,
            "a": candidates[p.a_index].text,
            "b": candidates[p.b_index].text,
        })

    system = (
        "You decide whether two H2 heading candidates are paraphrases of the "
        "same underlying question. Two candidates are paraphrases when an "
        "article that answered one would necessarily answer the other. "
        "Respond with a JSON array: [{k: int, paraphrase: bool}]. "
        "Be conservative — if the headings ask about different aspects "
        "(e.g., 'What is X' vs 'How does X work'), they are NOT paraphrases."
    )
    user = (
        "For each pair, answer paraphrase: true|false.\n"
        f"Pairs:\n{items}"
    )

    confirmed: set[tuple[int, int]] = set()
    try:
        result = await claude_json(system, user, max_tokens=1500, temperature=0.1)
        if isinstance(result, list):
            for entry in result:
                k = entry.get("k")
                is_para = entry.get("paraphrase")
                if isinstance(k, int) and 0 <= k < len(soft_pairs) and is_para is True:
                    p = soft_pairs[k]
                    confirmed.add((p.a_index, p.b_index))
    except Exception as exc:
        logger.warning("soft-pair arbitration failed, treating as distinct: %s", exc)

    return confirmed
