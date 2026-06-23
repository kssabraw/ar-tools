"""Silo discovery orchestration (PRD §7.1).

Sequence: grounding pass -> disambiguation gate -> demand sample + competitor
structure -> LLM silo proposal. Degraded modes follow PRD §16.2: a failed
demand sample or competitor scrape proceeds with a note; a failed grounding
pass halts (the caller turns the raised error into a session error).
"""

import logging
import math

from fanout.dataforseo import DataForSEOClient, DataForSEOError
from fanout.llm import LLMError, OpenAILLM
from fanout.pipeline.models import SiloDiscoveryResult

logger = logging.getLogger(__name__)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - (dot / (na * nb))


def _ambiguity_confirmed(
    seed: str, interpretations: list[str], llm: OpenAILLM, threshold: float
) -> bool:
    """Corroborate the LLM's ambiguity signal with embedding separation
    (PRD §7.1.2 / Q16). Confirmed only if the two most-distinct candidate
    interpretations are well-separated (cosine distance >= threshold). If the
    embeddings can't be computed, fall back to the LLM signal (ask the user)."""
    distinct = [i.strip() for i in interpretations if i.strip()]
    if len(distinct) < 2:
        return False
    try:
        vectors = llm.embed([f"{seed}: {i}" for i in distinct])
    except LLMError:
        return True
    max_distance = max(
        _cosine_distance(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    )
    return max_distance >= threshold


def run_silo_discovery(
    *,
    seed: str,
    topic_count: int,
    audience_hint: str | None,
    disambiguation_hint: str | None,
    llm: OpenAILLM,
    dfs: DataForSEOClient,
    serp_top_n: int = 5,
    ambiguity_separation_threshold: float = 0.5,
) -> SiloDiscoveryResult:
    # 1. Grounding — required. Failure halts the run (PRD §16.2).
    try:
        grounding = llm.ground_subject(seed, disambiguation_hint)
    except LLMError as exc:
        logger.error(
            "step_failed",
            extra={"event": "step_failed", "step": "silo_discovery", "reason": str(exc)},
        )
        raise

    detected_audience = audience_hint or grounding.detected_audience

    # 2. Disambiguation gate (PRD §7.1.2). The LLM's ambiguity signal is
    # corroborated by embedding separation before pausing, so a single
    # over-eager LLM flag doesn't spuriously interrupt the user.
    if (
        grounding.is_ambiguous
        and not disambiguation_hint
        and _ambiguity_confirmed(
            seed, grounding.interpretations, llm, ambiguity_separation_threshold
        )
    ):
        logger.info(
            "disambiguation_required",
            extra={
                "event": "disambiguation_required",
                "step": "silo_discovery",
                "interpretations": grounding.interpretations,
            },
        )
        return SiloDiscoveryResult(
            detected_audience=detected_audience,
            needs_disambiguation=True,
            interpretations=grounding.interpretations,
        )

    degraded: list[str] = []

    # 3. Demand sample — optional signal (PRD §16.2).
    demand_keywords: list[str] = []
    try:
        demand_keywords = dfs.keyword_ideas_sample(seed)
    except DataForSEOError as exc:
        degraded.append(
            "Demand sample unavailable for this run; silos based on grounding "
            "and competitor structure only."
        )
        logger.warning(
            "degraded",
            extra={"event": "degraded", "step": "demand_sample", "reason": str(exc)},
        )

    # 4. Competitor URL structure — optional signal (PRD §16.2).
    competitor_paths: list[str] = []
    try:
        competitor_paths = dfs.serp_competitor_paths(seed, top_n=serp_top_n)
    except DataForSEOError as exc:
        degraded.append(
            "Competitor structure unavailable for this run; silos based on demand "
            "signal and topic grounding only."
        )
        logger.warning(
            "degraded",
            extra={"event": "degraded", "step": "competitor_structure", "reason": str(exc)},
        )

    # 5. Silo proposal.
    silos = llm.propose_silos(
        seed=seed,
        topic_count=topic_count,
        audience=detected_audience,
        grounding_summary=grounding.summary,
        demand_keywords=demand_keywords,
        competitor_paths=competitor_paths,
    )
    if not silos:
        degraded.append(
            "The model did not return any valid silos. Try adjusting the seed or "
            "topic count, or add silos manually."
        )

    logger.info(
        "step_complete",
        extra={
            "event": "step_complete",
            "step": "silo_discovery",
            "silo_count": len(silos),
            "degraded": bool(degraded),
        },
    )
    return SiloDiscoveryResult(
        detected_audience=detected_audience,
        silos=silos,
        degraded_notes=degraded,
        aliases=grounding.aliases,
        peer_entities=grounding.peer_entities,
    )
