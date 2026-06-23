"""Cross-topic dedup pass (PRD §7.10.4), deterministic.

After every topic is planned, one pass over the full article set catches
cross-topic collisions: pairs of articles (in different topics) whose primary
keywords are near-identical (cosine > 0.85) OR whose top-3 SERP URLs overlap
(≥ 2 of 3). For each collision the article in the higher-relevance topic wins;
the loser article is dropped (its keywords stay active + unassigned in their
topic — no data is lost), and the losing topic's most-similar surviving article
gets a peer link to the winner so the topics stay connected. All decisions are
logged.

Implemented deterministically rather than as an LLM call: every input
(embeddings, SERPs, topic relevance) is already in hand, so this is reproducible
and testable against the §15.2 acceptance criterion.
"""

import logging

import numpy as np

from .models import ArticleRecord, PlanResult, TopicPlan

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _serp_overlap_top3(a: ArticleRecord, b: ArticleRecord) -> int:
    sa = {u.rstrip("/") for u in (a.serp_top_urls or [])[:3]}
    sb = {u.rstrip("/") for u in (b.serp_top_urls or [])[:3]}
    return len(sa & sb)


def cross_topic_dedup(
    result: PlanResult,
    *,
    topic_embeddings: dict[str, list[float] | None],
    embed_fn,
    primary_cosine_threshold: float = 0.85,
    serp_overlap_min: float = 2 / 3,
) -> None:
    """Mutate `result` in place: drop loser articles, set peer links, fill
    result.dedup_log. `embed_fn(list[str]) -> list[list[float]]`."""
    articles: list[ArticleRecord] = [a for p in result.per_topic for a in p.articles]
    if len(articles) < 2:
        result.dedup_log = {"collisions": [], "articles": len(articles)}
        return

    primaries = [a.primary_keyword for a in articles]
    try:
        raw = embed_fn(primaries)
        vectors = [np.asarray(v, dtype=np.float32) for v in raw]
    except Exception as exc:  # noqa: BLE001 — dedup is best-effort; never sink the run
        logger.warning(
            "degraded",
            extra={"event": "degraded", "step": "cross_topic_dedup",
                   "reason": f"primary embedding failed: {exc}"},
        )
        result.dedup_log = {"collisions": [], "error": "embedding_failed"}
        return
    # A short/over-long embedding batch would desync vectors from articles and
    # IndexError mid-loop; skip dedup rather than crash a successful plan (M3).
    if len(vectors) != len(articles):
        logger.warning(
            "degraded",
            extra={"event": "degraded", "step": "cross_topic_dedup",
                   "reason": f"embedding count mismatch ({len(vectors)} != {len(articles)})"},
        )
        result.dedup_log = {"collisions": [], "error": "embedding_count_mismatch"}
        return

    topic_vecs = {
        tid: np.asarray(v, dtype=np.float32) if v is not None else None
        for tid, v in topic_embeddings.items()
    }
    # Lever 2: remove the common-mode component (the shared seed direction that
    # dominates every silo embedding) before judging which silo a collided
    # article belongs to. Subtracting the mean of the topic vectors penalizes
    # silos that merely align with the broad seed and rewards the silo whose
    # *distinctive* direction matches the keyword — so e.g. "how does X work"
    # wins for the mechanism silo instead of losing to a broader silo.
    present = [v for v in topic_vecs.values() if v is not None]
    mean_vec = np.mean(np.stack(present), axis=0) if present else None

    # serp-overlap collision needs ≥ ceil(serp_overlap_min * 3) of the top 3.
    serp_min_count = int(np.ceil(serp_overlap_min * 3))
    dropped_ids: set[int] = set()
    collisions: list[dict] = []

    for i in range(len(articles)):
        if i in dropped_ids:
            continue
        for j in range(i + 1, len(articles)):
            if j in dropped_ids:
                continue
            ai, aj = articles[i], articles[j]
            if ai.topic_id == aj.topic_id:
                continue
            cos = _cosine(vectors[i], vectors[j])
            overlap = _serp_overlap_top3(ai, aj)
            if cos <= primary_cosine_threshold and overlap < serp_min_count:
                continue
            # Collision. Winner = the article more relevant to its own topic, by
            # the common-mode-removed (discriminative) relevance.
            rel_i = _relevance(vectors[i], topic_vecs.get(ai.topic_id), mean_vec)
            rel_j = _relevance(vectors[j], topic_vecs.get(aj.topic_id), mean_vec)
            if rel_j > rel_i:
                winner, loser, loser_idx = aj, ai, i
            else:
                winner, loser, loser_idx = ai, aj, j
            dropped_ids.add(loser_idx)
            _link_losing_topic(result, loser, winner)
            collisions.append({
                "winner": winner.primary_keyword,
                "winner_topic": winner.topic_id,
                "loser": loser.primary_keyword,
                "loser_topic": loser.topic_id,
                "cosine": round(cos, 4),
                "serp_overlap_top3": overlap,
                "winner_relevance": round(max(rel_i, rel_j), 4),
            })
            if loser_idx == i:
                break  # i was dropped; move to the next i

    if dropped_ids:
        drop_set = {id(articles[k]) for k in dropped_ids}
        for plan in result.per_topic:
            plan.articles = [a for a in plan.articles if id(a) not in drop_set]

    result.dedup_log = {"collisions": collisions, "articles": len(articles),
                        "dropped": len(dropped_ids)}
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "cross_topic_dedup",
               "articles": len(articles), "collisions": len(collisions),
               "dropped": len(dropped_ids)},
    )


def _relevance(primary_vec: np.ndarray, topic_vec: np.ndarray | None,
               mean_vec: np.ndarray | None = None) -> float:
    if topic_vec is None:
        return 0.0
    if mean_vec is not None:
        return _cosine(primary_vec - mean_vec, topic_vec - mean_vec)
    return _cosine(primary_vec, topic_vec)


def _link_losing_topic(result: PlanResult, loser: ArticleRecord, winner: ArticleRecord) -> None:
    """Give the losing topic a peer link to the winner (PRD §7.10.4): attach it to
    a surviving article in the loser's topic, preferring one that isn't the loser.
    Persistence resolves peer_primary_keywords to cluster ids."""
    loser_plan: TopicPlan | None = next(
        (p for p in result.per_topic if p.topic_id == loser.topic_id), None
    )
    if loser_plan is None:
        return
    survivors = [a for a in loser_plan.articles if a is not loser]
    if not survivors:
        return
    # The single most-related surviving article carries the link (architecture
    # later prioritizes/expands lateral links).
    anchor = survivors[0]
    if winner.primary_keyword not in anchor.peer_primary_keywords:
        anchor.peer_primary_keywords.append(winner.primary_keyword)
    if anchor.primary_keyword not in winner.peer_primary_keywords:
        winner.peer_primary_keywords.append(anchor.primary_keyword)
