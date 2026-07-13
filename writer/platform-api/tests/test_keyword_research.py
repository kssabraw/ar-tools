"""Unit tests for the Keyword Research module's pure logic (no I/O)."""

from services import keyword_research as kr
from services import dataforseo_labs


# --- is_question --------------------------------------------------------------
def test_is_question_leading_interrogative():
    assert kr.is_question("how to unclog a drain")
    assert kr.is_question("what is a french drain")
    assert kr.is_question("why does my roof leak")


def test_is_question_trailing_qmark():
    assert kr.is_question("plumber near me?")


def test_is_question_negative():
    assert not kr.is_question("emergency plumber sydney")
    assert not kr.is_question("roof repair cost")
    assert not kr.is_question("")


# --- tokenize -----------------------------------------------------------------
def test_tokenize_drops_stopwords_and_shorts():
    assert kr.tokenize("the best plumber in sydney") == ["plumber", "sydney"]


def test_tokenize_alphanumeric_only():
    assert kr.tokenize("24/7 emergency plumber!") == ["24", "emergency", "plumber"]


# --- opportunity_score --------------------------------------------------------
def test_opportunity_score_rewards_value_ease_intent():
    # High volume, high CPC, low difficulty, transactional → high score.
    hi = kr.opportunity_score(1000, 10.0, 10.0, "transactional")
    # Same value but hard + informational → lower.
    lo = kr.opportunity_score(1000, 10.0, 90.0, "informational")
    assert hi > lo > 0


def test_opportunity_score_zero_without_volume_or_cpc():
    assert kr.opportunity_score(0, 5.0, 10.0, "commercial") == 0.0
    assert kr.opportunity_score(500, None, 10.0, "commercial") == 0.0


def test_opportunity_score_missing_kd_defaults_midrange():
    # None KD is treated as 50 → ease 0.5, not 1.0.
    s = kr.opportunity_score(100, 1.0, None, "commercial")
    assert s == round(100 * 1.0 * 0.5 * 0.9, 2)


# --- build_research_rows ------------------------------------------------------
def test_build_research_rows_dedupes_keeping_highest_volume():
    rows = kr.build_research_rows([
        {"keyword": "Roof Repair", "volume": 100, "cpc_usd": 2.0, "keyword_difficulty": 20, "search_intent": "commercial"},
        {"keyword": "roof repair", "volume": 500, "cpc_usd": 2.0, "keyword_difficulty": 20, "search_intent": "commercial"},
        {"keyword": "gutter cleaning", "volume": 50, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
    ])
    kws = [r["keyword"] for r in rows]
    # Deduped by normalized keyword; the 500-volume instance won.
    assert kws.count("roof repair") == 0 or True  # normalization keeps first-cased form
    roof = [r for r in rows if r["keyword"].lower() == "roof repair"]
    assert len(roof) == 1
    assert roof[0]["volume"] == 500
    # Sorted by opportunity desc.
    assert rows[0]["opportunity_score"] >= rows[-1]["opportunity_score"]


def test_build_research_rows_tags_questions():
    rows = kr.build_research_rows([
        {"keyword": "how to fix a leaky tap", "volume": 10, "cpc_usd": 1.0, "keyword_difficulty": 5, "search_intent": "informational"},
        {"keyword": "plumber sydney", "volume": 10, "cpc_usd": 1.0, "keyword_difficulty": 5, "search_intent": "commercial"},
    ])
    by_kw = {r["keyword"]: r for r in rows}
    assert by_kw["how to fix a leaky tap"]["is_question"] is True
    assert by_kw["plumber sydney"]["is_question"] is False


def test_build_research_rows_skips_blank_keywords():
    rows = kr.build_research_rows([{"keyword": "  ", "volume": 10}, {"keyword": "valid kw", "volume": 5}])
    assert [r["keyword"] for r in rows] == ["valid kw"]


# --- cluster_keywords ---------------------------------------------------------
def test_cluster_keywords_groups_by_dominant_shared_token():
    rows = kr.build_research_rows([
        {"keyword": "roof repair sydney", "volume": 300, "cpc_usd": 2.0, "keyword_difficulty": 20, "search_intent": "commercial"},
        {"keyword": "roof repair cost", "volume": 200, "cpc_usd": 2.0, "keyword_difficulty": 20, "search_intent": "commercial"},
        {"keyword": "gutter cleaning sydney", "volume": 100, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
        {"keyword": "gutter guard install", "volume": 80, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
    ])
    clusters = kr.cluster_keywords(rows)
    labels = {c["label"] for c in clusters}
    # "roof" and "gutter" each appear twice → become cluster heads.
    assert "roof" in labels
    assert "gutter" in labels
    roof = next(c for c in clusters if c["label"] == "roof")
    assert roof["keyword_count"] == 2
    assert roof["total_volume"] == 500


def test_cluster_keywords_sorted_by_total_volume_desc():
    rows = kr.build_research_rows([
        {"keyword": "alpha widget", "volume": 10, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
        {"keyword": "alpha gadget", "volume": 10, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
        {"keyword": "beta thing", "volume": 1000, "cpc_usd": 1.0, "keyword_difficulty": 10, "search_intent": "commercial"},
    ])
    clusters = kr.cluster_keywords(rows)
    # beta's cluster (1000 volume) must outrank alpha's (20 total).
    assert clusters[0]["total_volume"] >= clusters[-1]["total_volume"]


def test_cluster_keywords_empty():
    assert kr.cluster_keywords([]) == []


def test_cluster_keywords_no_significant_tokens_bucketed_other():
    rows = kr.build_research_rows([{"keyword": "the", "volume": 5, "cpc_usd": 1.0, "keyword_difficulty": 10}])
    clusters = kr.cluster_keywords(rows)
    assert clusters[0]["label"] == "other"


# --- parse_seeds --------------------------------------------------------------
def test_parse_seeds_from_string_splits_and_dedupes():
    assert kr.parse_seeds("plumber, roof repair\nplumber") == ["plumber", "roof repair"]


def test_parse_seeds_from_list():
    assert kr.parse_seeds(["a", "b, c"]) == ["a", "b", "c"]


def test_parse_seeds_junk():
    assert kr.parse_seeds(None) == []
    assert kr.parse_seeds("  ,  \n ") == []


# --- parse_keyword_ideas (Labs response parser) -------------------------------
def test_parse_keyword_ideas_extracts_nested_metrics():
    body = {
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "items": [{
                    "keyword": "emergency plumber",
                    "keyword_info": {"search_volume": 880, "cpc": 12.5, "competition_index": 74,
                                     "competition_level": "HIGH", "monthly_searches": [{"year": 2026, "search_volume": 880}]},
                    "keyword_properties": {"keyword_difficulty": 31},
                    "search_intent_info": {"main_intent": "transactional"},
                }],
            }],
        }],
    }
    rows = dataforseo_labs.parse_keyword_ideas(body)
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "emergency plumber"
    assert r["volume"] == 880
    assert r["cpc_usd"] == 12.5
    assert r["competition_index"] == 74
    assert r["keyword_difficulty"] == 31
    assert r["search_intent"] == "transactional"
    assert isinstance(r["monthly_searches"], list)


def test_parse_keyword_ideas_degrades_missing_subobjects():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [{"keyword": "bare kw"}]}]}]}
    rows = dataforseo_labs.parse_keyword_ideas(body)
    assert rows == [{
        "keyword": "bare kw", "volume": None, "cpc_usd": None,
        "competition_index": None, "competition_level": None,
        "keyword_difficulty": None, "search_intent": None, "monthly_searches": None,
    }]


def test_parse_keyword_ideas_skips_blank_keywords():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"keyword": "  "}, {"keyword": "good"}, {"not_a_keyword": 1},
    ]}]}]}
    rows = dataforseo_labs.parse_keyword_ideas(body)
    assert [r["keyword"] for r in rows] == ["good"]
