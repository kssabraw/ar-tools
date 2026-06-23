"""Orphan keyword promotion (owner-requested follow-up to §7.10).

After every planning pass finishes (orchestrator -> peer-grouping -> split ->
dedup), some active keywords are silently NOT in any article — the orchestrator
chose to omit them (singletons, redundant long-tail) without formally dropping
them (no `orchestrator_drop_reason`), and cross-topic dedup loses the loser
article's supporting keywords. The user saw this with "what is retatrutide" —
a foundational query in the pool with relevance 0.72, not in any cluster.

On retatrutide this affected 44% of the active pool (679 of 1,541). This pass
catches every active keyword that ended up neither in an article nor formally
dropped and promotes it to its own singleton article (primary = the keyword,
supporting = []). Zero LLM / embedding cost — pure-compute set arithmetic.

Coverage is checked GLOBALLY (across all topics' articles), not per-topic, so
keywords pulled across silos by cross-topic peer-grouping are correctly
accounted for and don't get double-promoted.

Quality floor: by default, only orphans whose silo-anchor relevance score is
>= `orphan_promotion_min_score` are promoted (cf. `Settings`). Active keywords
below the bar stay as orphans (status='active', cluster_id=NULL) — they're
still in the table for Owner inspection / re-routing, just not turned into
editorial-thin singleton articles.
"""

import logging

from .models import DEFAULT_INTENT, ArticleRecord, PlanResult, TopicInput

logger = logging.getLogger(__name__)


def promote_orphans(
    result: PlanResult,
    topics: list[TopicInput],
    *,
    min_score: float = 0.0,
) -> None:
    """Mutate `result` in place: every active keyword that isn't covered by an
    article (anywhere in the plan), wasn't formally dropped, AND meets
    `min_score` becomes its own singleton article in its routed topic.

    `min_score` is checked against each topic's `keyword_relevance` map (the
    relevance score the gate recorded for the keyword in that topic). A keyword
    with no score recorded (defensive — shouldn't happen if the caller populates
    `keyword_relevance` from active rows) is NOT promoted, on the conservative
    side. With `min_score=0` the check is a no-op (promote-everything).

    Idempotent — re-running with the same input yields the same articles."""
    # Coverage is checked GLOBALLY so a keyword peer-grouped to a different
    # silo is still considered covered (not promoted again).
    covered: set[str] = set()
    dropped: set[str] = set()
    for plan in result.per_topic:
        for art in plan.articles:
            covered.add(art.primary_keyword)
            covered.update(art.supporting_keywords)
        for d in plan.dropped:
            dropped.add(d.keyword)

    topic_inputs_by_id = {t.id: t for t in topics}
    total_added = 0
    total_below_floor = 0
    for plan in result.per_topic:
        topic_input = topic_inputs_by_id.get(plan.topic_id)
        if topic_input is None:
            continue
        # The topic's full active pool = union of all its Louvain groupings'
        # keywords (groupings are what the orchestrator received).
        all_active: set[str] = set()
        for g in topic_input.groupings:
            all_active.update(g.keywords)
        candidates = sorted(all_active - covered - dropped)
        if not candidates:
            continue

        scores = topic_input.keyword_relevance
        promoted: list[str] = []
        below_floor = 0
        for kw in candidates:
            # min_score=0 disables the floor entirely (legacy behavior).
            if min_score > 0.0:
                score = scores.get(kw)
                if score is None or score < min_score:
                    below_floor += 1
                    continue
            promoted.append(kw)

        for orphan in promoted:
            plan.articles.append(ArticleRecord(
                topic_id=plan.topic_id,
                primary_keyword=orphan,
                supporting_keywords=[],
                intent=DEFAULT_INTENT,
                suggested_h2s=[],
                source_statistical_grouping_id=None,
                orchestrator_notes="Promoted orphan: not assigned by the orchestrator.",
            ))
        if promoted:
            plan.log["orphans_promoted"] = len(promoted)
        if below_floor:
            plan.log["orphans_below_floor"] = below_floor
        total_added += len(promoted)
        total_below_floor += below_floor
        # Update the global covered set so a later topic-loop iteration doesn't
        # treat this topic's orphans as still-uncovered.
        covered.update(promoted)

    if total_added or total_below_floor:
        logger.info(
            "step_complete",
            extra={"event": "step_complete", "step": "orphan_promotion",
                   "orphans_promoted": total_added,
                   "orphans_below_floor": total_below_floor,
                   "min_score": min_score},
        )
