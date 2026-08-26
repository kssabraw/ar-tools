"""Unit tests for the Keyword Research blog-topic generator's pure logic."""

from services import keyword_research_content as content


def test_select_topic_keywords_excludes_non_buyer():
    rows = [
        {"keyword": "become an adjuster", "audience_fit": "job_seeker",
         "search_intent": "informational", "opportunity_score": 99, "volume": 999},
        {"keyword": "tpa outsourcing", "audience_fit": "buyer",
         "search_intent": "informational", "opportunity_score": 3, "volume": 10},
    ]
    sel = [r["keyword"] for r in content.select_topic_keywords(rows)]
    assert "become an adjuster" not in sel
    assert "tpa outsourcing" in sel


def test_select_topic_keywords_prefers_informational_then_opportunity():
    rows = [
        {"keyword": "info-hi", "audience_fit": "buyer", "search_intent": "informational",
         "opportunity_score": 1, "volume": 1},
        {"keyword": "commercial-hi", "audience_fit": "buyer", "search_intent": "commercial",
         "opportunity_score": 50, "volume": 50},
        {"keyword": "question", "audience_fit": "buyer", "is_question": True,
         "opportunity_score": 0, "volume": 0},
    ]
    sel = [r["keyword"] for r in content.select_topic_keywords(rows)]
    # informational/question rank above commercial regardless of opportunity
    assert sel.index("info-hi") < sel.index("commercial-hi")
    assert sel.index("question") < sel.index("commercial-hi")


def test_select_topic_keywords_defaults_missing_audience_to_buyer():
    rows = [{"keyword": "no-tag", "search_intent": "informational"}]
    assert [r["keyword"] for r in content.select_topic_keywords(rows)] == ["no-tag"]


def test_clean_topics_dedupes_and_shapes():
    raw = [
        {"title": "A Great Post", "angle": "why", "target_keywords": ["k1", "k2"]},
        {"title": "a great post", "angle": "dup"},   # case-insensitive dup
        {"title": "", "angle": "blank"},             # dropped
        {"title": "Second", "angle": "x"},
    ]
    out = content._clean_topics(raw, cap=10)
    assert [t["title"] for t in out] == ["A Great Post", "Second"]
    assert out[0]["target_keywords"] == ["k1", "k2"]


def test_clean_topics_respects_cap():
    raw = [{"title": f"t{i}", "angle": "a"} for i in range(20)]
    assert len(content._clean_topics(raw, cap=5)) == 5


def test_build_topic_prompt_includes_keywords_and_count():
    p = content.build_topic_prompt("Business: X", [{"keyword": "tpa outsourcing", "volume": 40}], 8)
    assert "tpa outsourcing" in p
    assert "8 blog post ideas" in p
