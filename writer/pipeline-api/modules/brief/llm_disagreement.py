"""LLM Fan-Out Disagreement Analysis (PRD v2.6).

Industry-blind-spot mitigation: surface query expansions that ONE or
TWO of the four fan-out LLMs proposed but the rest didn't. Disagreement
is high signal - when chatgpt and gemini both surface a topic but
claude and perplexity don't, it usually means the topic sits on the
edge of well-documented territory and is worth flagging to a strategist
even when MMR doesn't pick it.

This stage runs purely on the existing fan-out output (no new LLM
calls). It's deterministic compute, ~100 lines, fast.

Output:
    `DisagreementAnalysis` carrying:
      - contested_topics: list of (text, surfaced_by, missed_by, score)
        tuples ranked by how strongly the disagreement signal points at
        a non-obvious topic.
      - consensus_strength: float in [0, 1]; higher means the four LLMs
        broadly agreed on this keyword's expansions (low blind-spot
        risk). Lower means there's significant disagreement that the
        contested_topics list is worth reading.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .parsers import levenshtein_ratio, normalize_text

logger = logging.getLogger(__name__)


# How many distinct LLMs (out of the 4 fan-out sources) must surface a
# topic for it to count as "consensus." Topics surfaced by FEWER than
# this count are candidates for the contested_topics list.
CONSENSUS_THRESHOLD = 3


@dataclass
class ContestedTopic:
    """A query expansion only some of the fan-out LLMs surfaced."""

    text: str
    surfaced_by: list[str]  # LLM IDs that proposed this text
    missed_by: list[str]    # LLM IDs that didn't
    score: float            # 0-1 (higher = more interesting disagreement)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "surfaced_by": self.surfaced_by,
            "missed_by": self.missed_by,
            "score": round(self.score, 4),
        }


@dataclass
class DisagreementAnalysis:
    contested_topics: list[ContestedTopic] = field(default_factory=list)
    consensus_strength: float = 0.0
    available: bool = False  # False when fewer than 2 LLMs returned data

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "consensus_strength": round(self.consensus_strength, 4),
            "contested_topics": [t.to_dict() for t in self.contested_topics],
        }


def _fuzzy_dedupe_key(text: str, existing_keys: list[str]) -> Optional[str]:
    """Find an existing key that's a near-duplicate via Levenshtein.

    Returns the matching key (so caller can group under it), or None
    when no near-duplicate exists. Threshold matches Step 4 aggregation.
    """
    norm = normalize_text(text)
    if not norm:
        return None
    for key in existing_keys:
        if levenshtein_ratio(norm, key) <= 0.15:
            return key
    return None


def analyze_fanout_disagreement(
    fanout_by_source: dict[str, list[str]],
    *,
    max_contested: int = 15,
) -> DisagreementAnalysis:
    """Find query expansions surfaced by < CONSENSUS_THRESHOLD LLMs.

    `fanout_by_source` is the same dict the brief pipeline already
    builds - keyed by `llm_fanout_<id>`, values are query strings each
    LLM proposed.

    Returns `DisagreementAnalysis(available=False, ...)` when fewer
    than 2 LLMs returned data (no comparison possible).
    """
    # Filter out failed/empty sources. The fan-out is keyed
    # `llm_fanout_chatgpt`, `llm_fanout_claude`, etc.
    populated_sources = {
        src: queries
        for src, queries in fanout_by_source.items()
        if queries and src.startswith("llm_fanout_")
    }
    if len(populated_sources) < 2:
        logger.info(
            "brief.llm_disagreement.skipped",
            extra={"reason": "fewer_than_two_llms", "count": len(populated_sources)},
        )
        return DisagreementAnalysis(available=False)

    # Group near-duplicate queries across LLMs by Levenshtein.
    # `groups[key]` → {"text": canonical, "sources": set of llm_ids}
    groups: dict[str, dict] = {}
    keys: list[str] = []  # ordered for deterministic dedup pass
    for source, queries in populated_sources.items():
        llm_id = source.replace("llm_fanout_", "")
        for q in queries:
            text = (q or "").strip()
            if not text:
                continue
            existing_key = _fuzzy_dedupe_key(text, keys)
            if existing_key is None:
                norm = normalize_text(text)
                if not norm:
                    continue
                groups[norm] = {"text": text, "sources": {llm_id}}
                keys.append(norm)
            else:
                groups[existing_key]["sources"].add(llm_id)

    total_llms = len(populated_sources)
    all_llm_ids = sorted(s.replace("llm_fanout_", "") for s in populated_sources)

    contested: list[ContestedTopic] = []
    consensus_topic_count = 0
    for group in groups.values():
        surfaced = sorted(group["sources"])
        if len(surfaced) >= CONSENSUS_THRESHOLD:
            consensus_topic_count += 1
            continue
        missed = [llm for llm in all_llm_ids if llm not in surfaced]
        # Score: prefer topics surfaced by exactly 1 LLM (highest blind-
        # spot signal) over those surfaced by 2 of 4. Length and
        # specificity also factor in - a single short word is less
        # interesting than a multi-word phrase.
        rarity = 1.0 - (len(surfaced) / max(total_llms, 1))
        specificity = min(len(group["text"].split()) / 5.0, 1.0)
        score = 0.7 * rarity + 0.3 * specificity
        contested.append(ContestedTopic(
            text=group["text"],
            surfaced_by=surfaced,
            missed_by=missed,
            score=score,
        ))

    contested.sort(key=lambda t: t.score, reverse=True)
    contested = contested[:max_contested]

    total_topics = len(groups)
    consensus_strength = (
        consensus_topic_count / total_topics if total_topics else 0.0
    )

    logger.info(
        "brief.llm_disagreement.complete",
        extra={
            "llm_count": total_llms,
            "total_topics": total_topics,
            "consensus_topic_count": consensus_topic_count,
            "contested_topic_count": len(contested),
            "consensus_strength": round(consensus_strength, 4),
        },
    )
    return DisagreementAnalysis(
        contested_topics=contested,
        consensus_strength=consensus_strength,
        available=True,
    )
