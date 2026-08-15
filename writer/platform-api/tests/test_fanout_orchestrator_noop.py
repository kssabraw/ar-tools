"""Unit tests for the orchestrator-no-op guard (fanout article planning).

Regression cover for the BPC-157 failure: both silos returned a valid-but-empty
orchestrator plan (0 articles, 0 drops, not degraded), and orphan promotion then
turned the entire active pool into 2,000 one-keyword articles. `orchestrator_noop`
identifies that case so the caller recovers the statistical groupings as
passthrough instead."""

from fanout.pipeline.article_planning.models import (
    ArticleRecord,
    DroppedKeyword,
    TopicPlan,
)
from fanout.pipeline.article_planning.orchestrate_articles import orchestrator_noop


def _article(topic_id="t1"):
    return ArticleRecord(
        topic_id=topic_id,
        primary_keyword="bpc 157 dosage",
        supporting_keywords=["bpc-157 dosage guide"],
        intent="informational",
        suggested_h2s=[],
        source_statistical_grouping_id="t1:g0",
        orchestrator_notes="",
    )


def test_empty_non_degraded_silo_with_groupings_is_a_noop():
    plan = TopicPlan(topic_id="t1")  # no articles, no drops, not degraded
    assert orchestrator_noop(plan, had_groupings=True) is True


def test_silo_with_an_article_is_not_a_noop():
    # The intended orphan-promotion case (real articles + a long orphan tail) must
    # not be caught — only a totally empty plan is.
    plan = TopicPlan(topic_id="t1", articles=[_article()])
    assert orchestrator_noop(plan, had_groupings=True) is False


def test_silo_that_dropped_keywords_is_not_a_noop():
    # The orchestrator did work — it deliberately dropped everything as off-niche.
    plan = TopicPlan(topic_id="t1", dropped=[DroppedKeyword("junk kw", "off-niche")])
    assert orchestrator_noop(plan, had_groupings=True) is False


def test_silo_without_groupings_is_not_a_noop():
    # Nothing to recover — an empty topic legitimately plans nothing.
    plan = TopicPlan(topic_id="t1")
    assert orchestrator_noop(plan, had_groupings=False) is False


def test_already_degraded_silo_is_not_re_flagged():
    # A degraded silo already fell back to passthrough; don't touch it.
    plan = TopicPlan(topic_id="t1", degraded=True)
    assert orchestrator_noop(plan, had_groupings=True) is False
