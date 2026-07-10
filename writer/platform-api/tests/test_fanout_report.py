"""Unit tests for fanout.report — the pure keyword-research report builders
(stats aggregation + HTML rendering). No I/O, so no Supabase/LLM/PDF access."""

from fanout.report import (
    build_report_stats,
    fallback_summary,
    render_report_html,
)


def _kw(keyword, topic_id, *, status="active", volume=None, kd=None, cpc=None):
    return {
        "keyword": keyword, "topic_id": topic_id, "cluster_id": None,
        "status": status, "relevance_score": 0.9,
        "volume": volume, "keyword_difficulty": kd, "cpc_usd": cpc,
    }


TOPICS = [{"id": "t1", "name": "Emergency plumbing"}, {"id": "t2", "name": "Hot water"}]

ARCH = {
    "pillars": [
        {"topic_id": "t1", "title": "Emergency Plumbing", "target_keyword": "emergency plumber",
         "supporting_article_ids": ["c1"]},
    ],
    "supporting_articles": [
        {"article_id": "c1", "name": "Burst pipe repair", "parent_pillar_topic_id": "t1"},
    ],
}


def test_stats_rollup_totals_and_per_silo():
    keywords = [
        _kw("emergency plumber", "t1", volume=1000, kd=40, cpc=8.0),
        _kw("burst pipe", "t1", volume=500, kd=20, cpc=6.0),
        _kw("hot water repair", "t2", volume=300, kd=70, cpc=5.0),
        _kw("filtered", "t1", status="excluded", volume=99, kd=10),  # not active → excluded from target
    ]
    stats = build_report_stats(session={"seed_keyword": "plumber"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=ARCH)
    assert stats["total_keywords"] == 3          # the excluded one is dropped
    assert stats["total_silos"] == 2
    assert stats["total_volume"] == 1800         # 1000+500+300
    assert stats["metrics_present"] is True
    # Silos sorted by volume desc → t1 (1500) before t2 (300).
    assert [s["name"] for s in stats["silos"]] == ["Emergency plumbing", "Hot water"]
    t1 = stats["silos"][0]
    assert t1["count"] == 2 and t1["volume"] == 1500
    assert t1["avg_kd"] == 30.0                   # (40+20)/2
    assert t1["top_keyword"] == "emergency plumber"  # highest volume in the silo
    # Difficulty spread: 20 easy, 40 medium, 70 hard.
    assert stats["difficulty_spread"] == {"easy": 1, "medium": 1, "hard": 1}
    # Content plan from the architecture.
    assert stats["planned_pages"] == 2
    assert stats["content_plan"]["pillars"][0]["articles"] == ["Burst pipe repair"]


def test_top_opportunities_ranked_by_volume():
    keywords = [
        _kw("low", "t1", volume=100), _kw("high", "t1", volume=9000), _kw("mid", "t2", volume=500),
    ]
    stats = build_report_stats(session={"seed_keyword": "x"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=None)
    assert [o["keyword"] for o in stats["top_opportunities"]] == ["high", "mid", "low"]
    assert stats["planned_pages"] == 0


def test_falls_back_to_surviving_when_no_active():
    keywords = [_kw("a", "t1", status="covered", volume=10), _kw("b", "t1", status="excluded")]
    stats = build_report_stats(session={"seed_keyword": "x"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=None)
    assert stats["total_keywords"] == 2  # no 'active' rows → all surviving counted


def test_metrics_absent_when_no_volume():
    keywords = [_kw("a", "t1"), _kw("b", "t1")]
    stats = build_report_stats(session={"seed_keyword": "x"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=None)
    assert stats["metrics_present"] is False
    assert stats["total_volume"] == 0
    assert stats["avg_difficulty"] is None


def test_fallback_summary_mentions_counts():
    keywords = [_kw("a", "t1", volume=1000)]
    stats = build_report_stats(session={"seed_keyword": "roofing"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=ARCH)
    summary = fallback_summary(stats)
    assert "roofing" in summary and "1 topic silo" in summary
    assert "1,000 searches per month" in summary


def test_render_html_structure_and_escaping():
    keywords = [_kw("emergency <plumber>", "t1", volume=1000, kd=40, cpc=8.0)]
    stats = build_report_stats(session={"seed_keyword": "plumber"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=ARCH)
    html = render_report_html(stats=stats, exec_summary="A summary.",
                              agency_name="Amazing Rankings", client_name="Acme Plumbing",
                              generated_on="Jul 10, 2026")
    assert html.startswith("<!DOCTYPE html>") and "@media print" in html
    for marker in ("Keyword Research Report", "Executive summary", "At a glance",
                   "Topic silos", "Top opportunities", "Recommended content plan",
                   "Appendix", "Amazing Rankings", "Acme Plumbing"):
        assert marker in html, marker
    # HTML-escaped keyword (no raw angle brackets from data).
    assert "emergency &lt;plumber&gt;" in html
    assert "<plumber>" not in html


def test_render_html_notes_missing_metrics():
    keywords = [_kw("a", "t1")]
    stats = build_report_stats(session={"seed_keyword": "x"}, topics=TOPICS,
                               keywords=keywords, clusters=[], architecture_json=None)
    html = render_report_html(stats=stats, exec_summary="s", agency_name="AR",
                              client_name=None, generated_on="today")
    assert "were not fetched" in html  # the missing-metrics note renders
