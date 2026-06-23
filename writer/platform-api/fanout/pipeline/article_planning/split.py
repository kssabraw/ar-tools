"""Salience split: divide an over-large article into sub-articles (PRD §7.10).

The orchestrator (and direct mode) can leave a single article carrying hundreds
of keywords that actually span several sub-topics. This pass re-clusters such an
article's keywords by embedding similarity — reusing the §7.9 Louvain machinery at
a higher resolution — and, when it cleanly divides into multiple coherent
sub-communities, splits it into separate articles.

Design choices (see the chat decision):
- **Salience, not SERP overlap.** Keyword embeddings are already the clustering
  signal and are essentially free (no DataForSEO); a SERP-per-keyword pass would
  cost ~$3-4 + minutes per run. SERP-overlap confirmation can be layered on later.
- **Targeted, not global.** Only articles above `min_keywords` are considered, so
  coherent small articles are never touched.
- **No thin stubs.** Sub-communities below `min_subarticle_size` fold back into the
  largest sub-cluster, so the long-tail stays attached rather than shattering into
  singleton articles. A split only happens when ≥2 substantial sub-clusters remain.
- **Runs before cross-topic dedup**, so the new sub-article primaries are
  deduped against the rest of the plan like any other article.
"""

import logging

from fanout.pipeline.clustering import Grouping, cluster_topic

from .models import ArticleRecord, PlanResult

logger = logging.getLogger(__name__)


def _absorb_small(groupings: list[Grouping], min_size: int) -> list[Grouping]:
    """Keep only sub-clusters of at least `min_size`, folding the rest into the
    largest, so a split never produces thin stub articles. If NO sub-cluster meets
    `min_size` (the whole article shattered into dust), return a single grouping so
    the caller leaves the article whole rather than splitting it into stubs."""
    if len(groupings) <= 1:
        return groupings
    big = [g for g in groupings if g.size >= min_size]
    small = [g for g in groupings if g.size < min_size]
    if not big:
        # Nothing substantial — do NOT split into stubs; signal "no split" by
        # returning one grouping (the largest), which the caller treats as no-op.
        return [max(groupings, key=lambda g: g.size)]
    if not small:
        return big
    extra = [k for g in small for k in g.keywords]
    largest = max(big, key=lambda g: g.size)
    merged = Grouping(
        id=largest.id,
        keywords=largest.keywords + extra,
        representative=largest.representative,
        cohesion=largest.cohesion,
        size=largest.size + len(extra),
    )
    return [merged if g is largest else g for g in big]


def _split_article(
    topic_id: str,
    art: ArticleRecord,
    *,
    embed_fn,
    min_keywords: int,
    resolution: float,
    edge_threshold: float,
    min_subarticle_size: int,
) -> list[ArticleRecord]:
    """Return the sub-articles for `art` (just `[art]` if it shouldn't split)."""
    # De-duplicate texts defensively; the primary leads so it keeps its slot.
    keywords: list[str] = []
    seen: set[str] = set()
    for kw in [art.primary_keyword, *art.supporting_keywords]:
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    if len(keywords) <= min_keywords:
        return [art]

    try:
        embeddings = embed_fn(keywords)
    except Exception as exc:  # noqa: BLE001 — split is best-effort; keep the article whole
        logger.warning(
            "degraded",
            extra={"event": "degraded", "step": "salience_split",
                   "reason": f"embedding failed: {exc}"},
        )
        return [art]
    if not embeddings or len(embeddings) != len(keywords):
        # Embedding short/mismatched — leave the article intact rather than guess.
        return [art]

    groupings = cluster_topic(
        topic_id, keywords, embeddings,
        edge_threshold=edge_threshold, resolution=resolution,
    )
    groupings = _absorb_small(groupings, min_subarticle_size)
    if len(groupings) <= 1:
        return [art]  # didn't cleanly divide — keep as one article

    # The sub-cluster holding the original primary keeps that primary + its
    # editorial fields; the others become new articles led by their medoid.
    subs: list[ArticleRecord] = []
    keeper_idx = next(
        (i for i, g in enumerate(groupings) if art.primary_keyword in g.keywords), 0
    )
    for i, g in enumerate(groupings):
        if i == keeper_idx:
            primary = art.primary_keyword
            subs.append(ArticleRecord(
                topic_id=topic_id,
                primary_keyword=primary,
                supporting_keywords=[k for k in g.keywords if k != primary],
                intent=art.intent,
                suggested_h2s=art.suggested_h2s,
                source_statistical_grouping_id=art.source_statistical_grouping_id,
                orchestrator_notes=(art.orchestrator_notes
                                    + " | kept primary after salience split").strip(" |"),
                serp_top_urls=art.serp_top_urls,
                peer_primary_keywords=art.peer_primary_keywords,
            ))
        else:
            primary = g.representative
            subs.append(ArticleRecord(
                topic_id=topic_id,
                primary_keyword=primary,
                supporting_keywords=[k for k in g.keywords if k != primary],
                intent=art.intent,
                suggested_h2s=[],
                source_statistical_grouping_id=None,
                orchestrator_notes=f"Split from '{art.primary_keyword}' by salience.",
            ))
    return subs


def split_oversized_articles(
    result: PlanResult,
    *,
    embed_fn,
    min_keywords: int,
    resolution: float,
    edge_threshold: float,
    min_subarticle_size: int,
) -> None:
    """Mutate `result` in place: split over-large articles by salience. Records the
    number of articles added per topic in that topic's log under
    `salience_split_added` (surfaced in the orchestrator debug log)."""
    total_added = 0
    for plan in result.per_topic:
        rebuilt: list[ArticleRecord] = []
        for art in plan.articles:
            rebuilt.extend(_split_article(
                plan.topic_id, art, embed_fn=embed_fn, min_keywords=min_keywords,
                resolution=resolution, edge_threshold=edge_threshold,
                min_subarticle_size=min_subarticle_size,
            ))
        added = len(rebuilt) - len(plan.articles)
        if added > 0:
            plan.log["salience_split_added"] = added
            total_added += added
        plan.articles = rebuilt
    if total_added:
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "salience_split",
                   "articles_added": total_added},
        )
