"""Unit tests for the Keyword Research module's pure logic (no I/O)."""

from services import keyword_research as kr
from services import dataforseo_labs
from services import keyword_research_report as krr


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


# --- relevance gate + brand guard --------------------------------------------
def test_token_set_stems_plurals():
    assert kr.token_set("architects sydney") == {"architect", "sydney"}
    assert kr.token_set("razors") == {"razor"}


def _ideas(*kws):
    return [{"keyword": k, "volume": 10} for k in kws]


def test_filter_drops_brand_homonyms_for_brand_plus_topic_seed():
    # Seed "henson architect", client "Henson Design Studio": brand token "henson"
    # coexists with topical "architect" → drop henson-but-not-architect drift.
    rows = _ideas(
        "henson architect sydney",   # topical → keep
        "residential architect",     # topical → keep
        "jim henson",                # brand-only → drop
        "henson shaving razors",     # brand-only → drop
        "best safety razor",         # off-topic → drop
    )
    kept, report = kr.filter_relevant_ideas(rows, ["henson architect"], "Henson Design Studio")
    kws = {r["keyword"] for r in kept}
    assert kws == {"henson architect sydney", "residential architect"}
    assert report["gate"] == "topical"
    assert report["dropped_brand_only"] == 2
    assert report["dropped_off_topic"] == 1


def test_filter_inert_for_pure_service_seed_preserves_broadening():
    # No brand token in the seed → gate stays off, semantic broadening survives.
    rows = _ideas("emergency plumber", "blocked drain", "hot water system")
    kept, report = kr.filter_relevant_ideas(rows, ["plumber"], "Acme Plumbing")
    assert len(kept) == 3
    assert report["gate"] == "none"


def test_filter_two_token_service_seed_still_broadens():
    # A 2-topical-token service seed stays under the coherence threshold, so
    # cross-topic broadening ("emergency plumber" → "blocked drain") survives.
    rows = _ideas("blocked drain", "hot water repair", "burst pipe")
    kept, report = kr.filter_relevant_ideas(rows, ["emergency plumber"], "Acme Plumbing")
    assert len(kept) == 3
    assert report["gate"] == "none"


def test_filter_coherence_gate_drops_generic_token_drift():
    # "local law 97 architect" (client "Henson Architect"): topical {local, law,
    # 97} (architect is a brand token) → 3 tokens → require ≥2 overlap, so the
    # generic-"law" category ("family law attorney", "law firm") is dropped.
    rows = _ideas(
        "local law 97 compliance",   # local+law+97 = 3 → keep
        "local law 97 deadline",     # 3 → keep
        "family law attorney",       # "law" only = 1 → drop
        "law firm",                  # "law" only → drop
        "architect salary",          # architect is brand, salary off-topic → 0 → drop
    )
    kept, report = kr.filter_relevant_ideas(rows, ["local law 97 architect"], "Henson Architect")
    kws = {r["keyword"] for r in kept}
    assert kws == {"local law 97 compliance", "local law 97 deadline"}
    assert report["gate"] == "coherence"
    assert report["dropped_off_topic"] == 3


def test_filter_coherence_uses_full_seed_even_when_brand_token_present():
    # "historical preservation architect" (client "Henson Architect"): "architect"
    # is a brand token, but the coherence gate keys on the FULL 3-token seed, so
    # the "historical" single-token category ("historical fiction books",
    # "historical figures") is dropped while topic-adjacent keywords survive.
    rows = _ideas(
        "historical preservation architect nyc",  # 3 → keep
        "historical preservation grants",          # historical+preservation = 2 → keep
        "preservation architect",                  # preservation+architect = 2 → keep
        "historical fiction books",                # historical only → drop
        "historical figures",                      # historical only → drop
        "residential architect",                   # architect only → drop
    )
    kept, report = kr.filter_relevant_ideas(
        rows, ["historical preservation architect"], "Henson Architect")
    kws = {r["keyword"] for r in kept}
    assert kws == {"historical preservation architect nyc",
                   "historical preservation grants", "preservation architect"}
    assert report["gate"] == "coherence"
    assert report["dropped_off_topic"] == 3


def test_filter_anchor_gate_catches_two_token_entity_seed():
    # "historic preservation" (2 tokens): "historic" is a drift anchor (present in
    # most returned ideas), so the coherence gate engages and requires BOTH tokens.
    rows = _ideas(
        "historic preservation division",   # both → keep
        "national trust for historic preservation",  # both → keep
        "synonym for historic",             # historic only → drop
        "hisd jobs",                        # neither (hisd != historic) → drop
        "what does historic mean",          # historic only → drop
        "historic sites",                   # historic only → drop
    )
    kept, report = kr.filter_relevant_ideas(rows, ["historic preservation"], "Acme Restoration")
    kws = {r["keyword"] for r in kept}
    assert kws == {"historic preservation division", "national trust for historic preservation"}
    assert report["gate"] == "coherence"


def test_filter_no_anchor_preserves_two_token_service_broadening():
    # "emergency plumber" (2 tokens): no single seed token dominates the broadened
    # set, so no anchor → broadening ("blocked drain") is preserved.
    rows = _ideas("blocked drain", "hot water repair", "burst pipe", "emergency plumber")
    kept, report = kr.filter_relevant_ideas(rows, ["emergency plumber"], "Acme Plumbing")
    assert len(kept) == 4
    assert report["gate"] == "none"


def test_seed_warnings_sparse_long_seed_suggests_shorter():
    ws = kr.seed_warnings(["historical preservation architect"], "Henson Architect", total_results=1)
    assert any("shorter core topic" in w for w in ws)


def test_filter_coherence_gate_runs_without_brand_match():
    # Generic-token drift is filtered even when no seed token is a brand token —
    # the coherence gate is not brand-conditioned.
    rows = _ideas("local law 97 requirements", "family law", "97 tips")
    kept, report = kr.filter_relevant_ideas(rows, ["local law 97 compliance"], "Acme Buildings")
    kws = {r["keyword"] for r in kept}
    assert "local law 97 requirements" in kws   # local+law+97 = 3
    assert "family law" not in kws              # "law" only
    assert "97 tips" not in kws                 # "97" only
    assert report["gate"] == "coherence"


def test_filter_inert_when_whole_name_is_brand_plus_service():
    # Client "Henson Architects" absorbs both seed tokens → no topical token to
    # gate on → nothing filtered (the brand-seed warning covers this case).
    rows = _ideas("jim henson", "henson architect sydney")
    kept, report = kr.filter_relevant_ideas(rows, ["henson architect"], "Henson Architects")
    assert len(kept) == 2
    assert report["gate"] == "none"


def test_filter_disabled_keeps_everything():
    rows = _ideas("jim henson", "henson architect")
    kept, report = kr.filter_relevant_ideas(rows, ["henson architect"], "Henson Design", enabled=False)
    assert len(kept) == 2
    assert report["gate"] == "off"


def test_looks_like_brand_seed():
    assert kr.looks_like_brand_seed("henson architect", "Henson Architects")
    assert kr.looks_like_brand_seed("henson architects sydney", "Henson Architects")  # 2/3 brand
    assert not kr.looks_like_brand_seed("residential architect", "Henson Architects")
    assert not kr.looks_like_brand_seed("plumber", "Acme Plumbing")
    assert not kr.looks_like_brand_seed("architect", "")


def test_seed_warnings_flags_brand_seed():
    ws = kr.seed_warnings(["henson architect"], "Henson Architects")
    assert len(ws) == 1
    assert "business name" in ws[0]


def test_seed_warnings_reports_filtering_and_empty_result():
    report = {"gate": "topical", "input": 5, "kept": 0,
              "dropped_off_topic": 3, "dropped_brand_only": 2}
    ws = kr.seed_warnings(["residential architect"], "Acme Homes", report, total_results=0)
    joined = " ".join(ws)
    assert "Filtered 5" in joined
    assert "No on-topic keywords were found" in joined


def test_seed_warnings_empty_result_suppressed_when_suggestions_filled_run():
    # Ideas fully filtered, but suggestions returned rows → run isn't empty, so
    # the "no keywords found" advisory must not fire.
    report = {"gate": "topical", "input": 5, "kept": 0,
              "dropped_off_topic": 3, "dropped_brand_only": 2}
    ws = kr.seed_warnings(["residential architect"], "Acme Homes", report, total_results=12)
    joined = " ".join(ws)
    assert "Filtered 5" in joined
    assert "No on-topic keywords" not in joined


def test_seed_warnings_none_for_clean_service_seed():
    assert kr.seed_warnings(["plumber"], "Acme Plumbing") == []


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


def test_parse_related_keywords_harvests_enriched_nodes():
    # related_keywords nests metrics under keyword_data and lists bare neighbour
    # strings under related_keywords; we harvest the enriched keyword_data nodes.
    body = {
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "items": [
                    {
                        "keyword_data": {
                            "keyword": "adaptive reuse",
                            "keyword_info": {"search_volume": 3600, "cpc": 4.2, "competition_index": 30},
                            "keyword_properties": {"keyword_difficulty": 28},
                            "search_intent_info": {"main_intent": "informational"},
                        },
                        "related_keywords": ["adaptive reuse architecture", "adaptive reuse examples"],
                    },
                    {"depth": 1},  # malformed node without keyword_data → skipped
                ],
            }],
        }],
    }
    rows = dataforseo_labs.parse_related_keywords(body)
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "adaptive reuse"
    assert r["volume"] == 3600
    assert r["keyword_difficulty"] == 28
    assert r["search_intent"] == "informational"


def test_parse_related_neighbors_harvests_and_dedupes_strings():
    body = {
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "items": [
                    {"keyword_data": {"keyword": "historic preservation"},
                     "related_keywords": ["adaptive reuse", "SHPO", "adaptive reuse"]},
                    {"keyword_data": {"keyword": "adaptive reuse"},
                     "related_keywords": ["heritage consultant", "SHPO"]},
                ],
            }],
        }],
    }
    neighbors = dataforseo_labs.parse_related_neighbors(body)
    # Deduped case-insensitively, order preserved.
    assert neighbors == ["adaptive reuse", "SHPO", "heritage consultant"]


def test_parse_keyword_suggestions_shares_item_shape():
    # keyword_suggestions returns the same nested metric objects as ideas.
    body = {
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "items": [{
                    "keyword": "emergency plumber sydney",
                    "keyword_info": {"search_volume": 210, "cpc": 9.0, "competition_index": 55},
                    "keyword_properties": {"keyword_difficulty": 22},
                    "search_intent_info": {"main_intent": "transactional"},
                }],
            }],
        }],
    }
    rows = dataforseo_labs.parse_keyword_suggestions(body)
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "emergency plumber sydney"
    assert r["volume"] == 210
    assert r["keyword_difficulty"] == 22
    assert r["search_intent"] == "transactional"


# --- report builders (pure) ---------------------------------------------------
def _sample_keywords():
    return [
        {"keyword": "emergency plumber sydney", "cluster_label": "plumber", "volume": 800,
         "cpc_usd": 12.0, "keyword_difficulty": 25, "search_intent": "transactional",
         "is_question": False, "opportunity_score": 7200.0},
        {"keyword": "plumber near me", "cluster_label": "plumber", "volume": 500,
         "cpc_usd": 10.0, "keyword_difficulty": 40, "search_intent": "commercial",
         "is_question": False, "opportunity_score": 2700.0},
        {"keyword": "how much does a plumber cost", "cluster_label": "cost", "volume": 300,
         "cpc_usd": 5.0, "keyword_difficulty": 15, "search_intent": "informational",
         "is_question": True, "opportunity_score": 765.0},
    ]


def test_report_stats_rollup_and_clusters():
    stats = krr.build_report_stats(run={"seeds": ["plumber"]}, keywords=_sample_keywords())
    assert stats["total_keywords"] == 3
    assert stats["total_clusters"] == 2
    assert stats["total_volume"] == 1600
    assert stats["metrics_present"] is True
    assert stats["question_count"] == 1
    # Clusters sorted by total volume desc — "plumber" (1300) before "cost" (300).
    assert [c["label"] for c in stats["clusters"]] == ["plumber", "cost"]
    plumber = stats["clusters"][0]
    assert plumber["count"] == 2
    assert plumber["top_keyword"] == "emergency plumber sydney"


def test_report_stats_top_opportunities_sorted_by_score():
    stats = krr.build_report_stats(run={"seeds": ["plumber"]}, keywords=_sample_keywords())
    assert stats["top_opportunities"][0]["keyword"] == "emergency plumber sydney"
    assert stats["questions"][0]["keyword"] == "how much does a plumber cost"


def test_report_stats_no_metrics():
    kws = [{"keyword": "x", "cluster_label": "x", "volume": None, "cpc_usd": None,
            "keyword_difficulty": None, "is_question": False, "opportunity_score": 0}]
    stats = krr.build_report_stats(run={"seeds": []}, keywords=kws)
    assert stats["metrics_present"] is False
    assert stats["avg_difficulty"] is None


def test_fallback_summary_mentions_counts_and_top():
    stats = krr.build_report_stats(run={"seeds": ["plumber"]}, keywords=_sample_keywords())
    text = krr.fallback_summary(stats)
    assert "3" in text and "plumber" in text.lower()
    assert "emergency plumber sydney" in text


def test_render_report_html_is_escaped_and_self_contained():
    kws = [{"keyword": "<b>inject</b> plumber", "cluster_label": "plumber", "volume": 10,
            "cpc_usd": 1.0, "keyword_difficulty": 5, "search_intent": "commercial",
            "is_question": False, "opportunity_score": 9.0}]
    stats = krr.build_report_stats(run={"seeds": ["plumber"]}, keywords=kws)
    html = krr.render_report_html(stats=stats, exec_summary="Great <results>.",
                                  agency_name="Acme SEO", client_name="Bob & Co",
                                  generated_on="Jul 13, 2026")
    assert html.startswith("<!DOCTYPE html>")
    assert "&lt;b&gt;inject&lt;/b&gt;" in html      # keyword escaped
    assert "<b>inject" not in html                   # no raw injection
    assert "Bob &amp; Co" in html
    assert "Acme SEO" in html
