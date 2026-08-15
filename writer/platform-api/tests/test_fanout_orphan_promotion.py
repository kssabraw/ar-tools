"""Orphan promotion must skip a degraded silo (fanout article planning).

Regression cover for a follow-up to the BPC-157 fix: when the orchestrator-noop
guard converts an empty silo to statistical passthrough (degraded=True) and that
silo's groupings are singletons (passthrough yields no articles), orphan promotion
must NOT then mint one-keyword articles from the leftovers — that's the very
explosion passthrough exists to prevent. A non-degraded silo still promotes."""

from fanout.pipeline.article_planning.models import (
    ArticleRecord,
    GroupingInput,
    PlanResult,
    TopicInput,
    TopicPlan,
)
from fanout.pipeline.article_planning.orphan_promotion import promote_orphans


def _topic(tid, kws):
    return TopicInput(
        id=tid, name=tid, rationale="", relationship_type="", embedding=None,
        groupings=[GroupingInput(id=f"{tid}:g{i}", representative=k, cohesion=1.0,
                                 size=1, keywords=[k]) for i, k in enumerate(kws)],
        keyword_relevance={k: 0.9 for k in kws},
    )


def test_degraded_silo_is_not_orphan_promoted():
    topics = [_topic("t1", ["a", "b", "c"])]
    result = PlanResult(per_topic=[TopicPlan(topic_id="t1", degraded=True)])

    promote_orphans(result, topics, min_score=0.0)

    plan = result.per_topic[0]
    assert plan.articles == []  # nothing minted from the degraded silo
    assert plan.log.get("orphans_skipped_degraded") is True


def test_non_degraded_silo_still_promotes_orphans():
    topics = [_topic("t1", ["a", "b", "c"])]
    result = PlanResult(per_topic=[TopicPlan(topic_id="t1", degraded=False)])

    promote_orphans(result, topics, min_score=0.0)

    plan = result.per_topic[0]
    assert {a.primary_keyword for a in plan.articles} == {"a", "b", "c"}
    assert plan.log.get("orphans_promoted") == 3


def test_covered_keyword_in_a_degraded_silo_still_blocks_promotion_elsewhere():
    # A degraded silo's passthrough articles are real coverage: a keyword they
    # cover must not be re-promoted in another silo. (Guards the global covered
    # set staying intact even though the degraded silo itself is skipped.)
    topics = [_topic("t1", ["shared", "x"]), _topic("t2", ["shared", "y"])]
    covered_article = TopicPlan(
        topic_id="t1", degraded=True,
        articles=[
            # a passthrough-style article covering "shared" + "x"
            ArticleRecord(
                topic_id="t1", primary_keyword="shared", supporting_keywords=["x"],
                intent="informational", suggested_h2s=[],
                source_statistical_grouping_id="t1:g0", orchestrator_notes="",
            )
        ],
    )
    result = PlanResult(per_topic=[covered_article, TopicPlan(topic_id="t2", degraded=False)])

    promote_orphans(result, topics, min_score=0.0)

    t2 = result.per_topic[1]
    promoted = {a.primary_keyword for a in t2.articles}
    assert "shared" not in promoted  # already covered by the degraded silo
    assert promoted == {"y"}
