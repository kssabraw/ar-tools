"""Unit tests for the problem-first Topic Research engine's pure logic."""

from services import keyword_topic_research as tr


def test_aggregate_competitor_domains_excludes_client_and_orders_by_appearances():
    organic = [
        [{"domain": "sedgwick.com"}, {"domain": "crawco.com"}, {"domain": "bsaclaims.com"}],
        [{"domain": "sedgwick.com"}, {"domain": "gallagherbassett.com"}],
    ]
    doms = tr.aggregate_competitor_domains(organic, "bsaclaims.com", top_n=3)
    assert "bsaclaims.com" not in doms
    assert doms[0] == "sedgwick.com"          # 2 appearances
    assert set(doms) == {"sedgwick.com", "crawco.com", "gallagherbassett.com"}


def test_aggregate_competitor_domains_strips_www_and_dedupes_per_serp():
    organic = [[{"domain": "www.sedgwick.com"}, {"domain": "sedgwick.com"}]]
    doms = tr.aggregate_competitor_domains(organic, None, top_n=5)
    assert doms == ["sedgwick.com"]           # www stripped, counted once per SERP


def test_topic_priority_monotonic():
    assert tr.topic_priority(5000, 4, 2) > tr.topic_priority(50, 4, 2)      # volume
    assert tr.topic_priority(500, 8, 1) > tr.topic_priority(500, 0, 1)      # questions
    assert tr.topic_priority(500, 4, 3) > tr.topic_priority(500, 4, 0)      # competitors


def test_build_topic_card_drops_job_seeker_keeps_buyer():
    card = tr.build_topic_card(
        {"theme": "Claims leakage", "problem": "p", "title": "T", "search_query": "claims leakage"},
        [{"keyword": "claims leakage", "volume": 320},
         {"keyword": "adjuster salary", "volume": 9999},        # job-seeker → dropped
         {"keyword": "reduce claims leakage", "volume": 110}],
        ["what causes claims leakage"],
        ["sedgwick.com: claims leakage"],
    )
    kws = [k["keyword"] for k in card["supporting_keywords"]]
    assert "adjuster salary" not in kws
    assert {"claims leakage", "reduce claims leakage"} <= set(kws)
    assert card["volume_total"] == 430                          # excludes the job-seeker volume
    assert card["questions"] and card["competitor_examples"]
    assert card["title"] == "T"


def test_build_topic_card_title_falls_back_to_theme():
    card = tr.build_topic_card(
        {"theme": "Catastrophe staffing", "problem": "p", "search_query": "catastrophe staffing"},
        [], [], [])
    assert card["title"] == "Catastrophe staffing"


def test_rank_topics_drops_empty_and_sorts_by_priority():
    ranked = tr.rank_topics([
        {"theme": "a", "supporting_keywords": [], "questions": [], "priority": 0.9},   # empty → dropped
        {"theme": "b", "supporting_keywords": [{"keyword": "x"}], "questions": [], "priority": 0.5},
        {"theme": "c", "supporting_keywords": [], "questions": ["q"], "priority": 0.8},
    ])
    assert [c["theme"] for c in ranked] == ["c", "b"]


def test_match_competitor_examples_matches_shared_token():
    theme = {"theme": "Claims leakage", "search_query": "claims leakage"}
    competitors = [
        {"domain": "sedgwick.com", "sample": [
            {"keyword": "reducing claims leakage"}, {"keyword": "office holiday party"}]},
    ]
    ex = tr._match_competitor_examples(theme, competitors)
    assert ex == ["sedgwick.com: reducing claims leakage"]      # only the token-overlapping one
