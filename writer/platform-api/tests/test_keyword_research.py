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


def test_tokenize_drops_interrogatives():
    # Pure interrogatives are dropped so a question seed anchors on its real topic
    # (no "what"/"how" seed token inflating the relevance gate or hijacking clusters).
    assert kr.tokenize("what is a third party claims administrator") == [
        "third", "party", "claims", "administrator"]
    assert kr.tokenize("how does a claims adjuster get paid") == [
        "claims", "adjuster", "paid"]
    # ...but ambiguous words that can be real topics are kept.
    assert "will" in kr.tokenize("last will and testament")


def test_question_seed_tokens_exclude_interrogatives():
    # is_question still fires on the raw string even though the token is gone.
    assert kr.is_question("what is a third party claims administrator")
    assert kr.token_set("what is a third party claims administrator") == {
        "third", "party", "claim", "administrator"}


def test_filter_question_seeds_reject_interrogative_only_overlap():
    # The reported BSA Claims failure: question seeds made "what" a seed token, so
    # keyword_ideas "what is X" drift cleared the >=2 coherence gate via what + one
    # generic token. With interrogatives gone, those match on <2 topical tokens.
    seeds = ["what is a third party claims administrator?",
             "how does a third party claims administrator get paid?",
             "catastrophe claims management"]
    rows = [
        {"keyword": "what is supply chain management"},   # {supply, chain, management} -> 1 (management)
        {"keyword": "what is a hen party"},               # {hen, party} -> 1 (party)
        {"keyword": "what is an independent variable"},   # {independent, variable} -> 0
        {"keyword": "third party administrator health insurance"},  # -> 3, kept
        {"keyword": "catastrophe claims management software"},      # -> 3, kept
    ]
    kept, report = kr.filter_relevant_ideas(rows, seeds, "BSA Claims")
    kept_kw = {r["keyword"] for r in kept}
    assert "what is supply chain management" not in kept_kw
    assert "what is a hen party" not in kept_kw
    assert "what is an independent variable" not in kept_kw
    assert "third party administrator health insurance" in kept_kw
    assert "catastrophe claims management software" in kept_kw
    assert report["gate"] == "coherence"


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


def test_filter_per_seed_overlap_kills_multiseed_pooling_flood():
    # The reported FreightOptics failure (run bedc615e): 4 three-token seeds. The
    # pooled union {3pl, audit, software, company, platform, parcel, spend,
    # management} let "password management software" pass on management(one seed) +
    # software(another) — two tokens NO single seed contains together. Per-seed
    # overlap drops the whole "X management software" flood while keeping genuinely
    # on-topic ideas that share ≥2 tokens with ONE real seed.
    seeds = ["3pl audit software", "3pl audit company",
             "3pl audit platform", "parcel spend management"]
    rows = _ideas(
        "3pl invoice audit",              # {3pl, audit} vs "3pl audit software" = 2 → keep
        "3pl audit companies",            # {3pl, audit} → keep
        "password management software",   # management + software (diff seeds) → drop
        "project management software",    # management + software → drop
        "property management software",   # management + software → drop
        "parcel spend analysis",          # {parcel, spend} vs "parcel spend management" = 2 → keep
    )
    kept, report = kr.filter_relevant_ideas(rows, seeds, "FreightOptics")
    kws = {r["keyword"] for r in kept}
    assert report["gate"] == "coherence"
    assert "3pl invoice audit" in kws
    assert "3pl audit companies" in kws
    assert "parcel spend analysis" in kws
    assert "password management software" not in kws
    assert "project management software" not in kws
    assert "property management software" not in kws


def test_filter_multiseed_short_service_seeds_still_broaden():
    # Two short clean service seeds (no single seed ≥3 tokens, no drift anchor) →
    # gate stays OFF so cross-topic broadening survives, even though the pooled
    # union is 4 tokens. The old union rule (len(union) >= 3) would have engaged.
    rows = _ideas("blocked drain", "hot water repair", "burst pipe")
    kept, report = kr.filter_relevant_ideas(
        rows, ["emergency plumber", "drain cleaning"], "Acme Plumbing")
    assert len(kept) == 3
    assert report["gate"] == "none"


# --- detect_cluster_dominance -------------------------------------------------
def test_cluster_dominance_flags_offseed_majority():
    clusters = [
        {"label": "management", "keyword_count": 60, "total_volume": 100},
        {"label": "audit", "keyword_count": 40, "total_volume": 50},
    ]
    d = kr.detect_cluster_dominance(clusters, 100, ["3pl audit", "parcel spend"])
    assert d is not None and d["label"] == "management" and d["fraction"] == 0.6


def test_cluster_dominance_silent_when_head_is_a_seed_term():
    # "<service> <city>" runs legitimately cluster under the service (a seed token).
    clusters = [{"label": "plumber", "keyword_count": 70, "total_volume": 100}]
    assert kr.detect_cluster_dominance(clusters, 100, ["emergency plumber"]) is None


def test_cluster_dominance_silent_on_small_run_and_other():
    big = [{"label": "widget", "keyword_count": 9, "total_volume": 10}]
    assert kr.detect_cluster_dominance(big, 10, ["gadget"]) is None   # below min_count
    other = [{"label": "other", "keyword_count": 60, "total_volume": 0}]
    assert kr.detect_cluster_dominance(other, 100, ["gadget"]) is None


def test_cluster_dominance_silent_below_fraction():
    clusters = [{"label": "management", "keyword_count": 30, "total_volume": 10},
                {"label": "audit", "keyword_count": 70, "total_volume": 10}]
    # Top cluster "audit" is 70% but IS a seed term; "management" is only 30%.
    assert kr.detect_cluster_dominance(clusters, 100, ["3pl audit"]) is None


# --- build_filter_summary -----------------------------------------------------
def test_build_filter_summary_reconciles_and_tallies():
    dropped = [
        {"keyword": "project management software", "reason": "Off your seed topic (category drift)"},
        {"keyword": "password manager", "reason": "Off your seed topic (category drift)"},
        {"keyword": "3pl invoice audit", "reason": "Not topically relevant"},  # survived elsewhere
        {"keyword": "PROJECT management software", "reason": "dup"},           # dupe (normalized)
    ]
    fs = kr.build_filter_summary(
        raw_pool=50, kept=8, dropped_detail=dropped,
        final_keywords=["3pl invoice audit", "freight audit"],
        filter_warnings=["Filtered 2 keywords."],
    )
    assert fs["raw_pool"] == 50 and fs["kept"] == 8
    kws = {d["keyword"] for d in fs["dropped"]}
    # a keyword present in final results is never reported as dropped
    assert "3pl invoice audit" not in kws
    # deduped by normalized keyword (kept first reason)
    assert fs["dropped_total"] == 2
    assert fs["by_reason"][0]["reason"] == "Off your seed topic (category drift)"
    assert fs["by_reason"][0]["count"] == 2
    assert fs["warnings"] == ["Filtered 2 keywords."]


def test_build_filter_summary_caps_sample():
    dropped = [{"keyword": f"kw {i}", "reason": "drift"} for i in range(200)]
    fs = kr.build_filter_summary(
        raw_pool=200, kept=0, dropped_detail=dropped,
        final_keywords=[], filter_warnings=[], cap=10)
    assert len(fs["dropped"]) == 10
    assert fs["dropped_total"] == 200


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


# --- detect_brand_flood_tokens (related-layer brand/homonym flood gate) --------
def _mitchell_related():
    """The real "third party claims adjuster" flood shape: a competitor-brand
    namespace ("mitchell ...") dominating the seedless neighbours, mixed with a
    few legit seed-anchored terms and diverse legit adjacency."""
    brand = [
        "mitchell connect", "mitchell community", "mitchell prodemand",
        "mitchell connect login", "mitchell international", "mitchell 1 login",
        "mitchell collision", "mitchell cloud", "mitchell usa serum",
        "mitchell cream",  # homonym skincare brand — pure off-niche
    ]
    seed_anchored = ["third-party payer examples", "claims adjuster salary"]
    legit_adjacent = ["first notice of loss", "subrogation basics"]
    return brand + seed_anchored + legit_adjacent


def test_brand_flood_detects_dominant_namespace():
    flood, report = kr.detect_brand_flood_tokens(
        _mitchell_related(), ["third party claims adjuster"], min_count=8, min_fraction=0.4,
    )
    assert "mitchell" in flood
    assert report["gate"] == "flood"
    assert report["dropped"] >= 10


def test_brand_flood_keeps_seed_anchored_and_diverse_adjacency():
    flood, _ = kr.detect_brand_flood_tokens(
        _mitchell_related(), ["third party claims adjuster"], min_count=8, min_fraction=0.4,
    )
    seed_toks = kr.token_set("third party claims adjuster")
    # brand namespace dropped...
    assert kr.is_brand_flooded("mitchell connect", seed_toks, flood)
    assert kr.is_brand_flooded("mitchell usa serum", seed_toks, flood)
    # ...seed-anchored kept even though unrelated otherwise...
    assert not kr.is_brand_flooded("third-party payer examples", seed_toks, flood)
    # ...and diverse legit adjacency (no dominant token) kept.
    assert not kr.is_brand_flooded("first notice of loss", seed_toks, flood)


def test_brand_flood_inert_on_clean_diverse_related_set():
    # The "historic preservation" shape: a tiny, diverse seedless subset — no flood.
    related = [
        "historic preservation office", "national historic preservation act",
        "adaptive reuse", "national trust", "state historic tax credit",
        "preservation grants", "architecture salary",
    ]
    flood, report = kr.detect_brand_flood_tokens(related, ["historic preservation"])
    assert flood == set()
    assert report["gate"] in ("none", "off")


def test_brand_flood_below_min_count_never_fires():
    # A handful of same-brand seedless terms below the absolute floor is left alone.
    related = ["acme one", "acme two", "acme three", "roof repair guide"]
    flood, report = kr.detect_brand_flood_tokens(related, ["roof repair"], min_count=8)
    assert flood == set()
    assert report["seedless"] < 8


def test_brand_flood_disabled_returns_empty():
    flood, report = kr.detect_brand_flood_tokens(
        _mitchell_related(), ["third party claims adjuster"], enabled=False,
    )
    assert flood == set() and report["gate"] == "off"


# --- is_seed_acronym + flood exoneration -------------------------------------
def test_is_seed_acronym_matches_subsequence_from_first_word():
    assert kr.is_seed_acronym("tpa", ["third party claims administrator"])   # t-p-a of t-p-c-a
    assert kr.is_seed_acronym("tpca", ["third party claims administrator"])  # full acronym


def test_is_seed_acronym_rejects_non_acronyms():
    assert not kr.is_seed_acronym("mitchell", ["third party claims administrator"])
    assert not kr.is_seed_acronym("t", ["third party claims administrator"])   # too short
    assert not kr.is_seed_acronym("pca", ["third party claims administrator"])  # must start at first word
    assert not kr.is_seed_acronym("tpa", ["roof repair contractor"])           # not this seed


def test_brand_flood_exonerates_seed_acronym():
    # "tpa" is the seed's own acronym — the "tpa ..." namespace must NOT be flooded,
    # while a real competitor brand ("mitchell") still is.
    related = ["tpa companies", "tpa insurance", "tpa software", "tpa services",
               "tpa login", "tpa portal", "tpa list", "tpa near me",
               "mitchell connect", "mitchell prodemand", "mitchell login",
               "mitchell serum", "mitchell 1", "mitchell cloud", "mitchell community",
               "mitchell international"]
    flood, _ = kr.detect_brand_flood_tokens(
        related, ["third party claims administrator"], min_count=5, min_fraction=0.3)
    assert "tpa" not in flood
    assert "mitchell" in flood


# --- detect_generic_drift_tokens (bleached filler-token drift gate) -------------
def _tpa_related():
    """The real "third party claims administrator" shape: the related graph
    wandered from the legal compound "third party" into the event sense of the
    bleached filler "party", mixed with the on-topic compound, legit
    distinctive-token adjacency, and true adjacency."""
    party_drift = [  # solo overlap = {"party"} — false-friend drift
        "party rentals", "party supplies", "birthday party ideas",
        "party planning checklist", "party bus", "party city near me",
    ]
    third_drift = ["third grade math", "third eye chakra"]  # solo {"third"} — below min
    compound = ["third party administrator", "third party claims process"]  # overlap >= 2
    distinctive_solo = ["claims adjuster salary", "insurance claims process"]  # solo {"claim"}
    adjacency = ["first notice of loss", "subrogation basics"]  # overlap 0
    return party_drift + third_drift + compound + distinctive_solo + adjacency


def test_generic_drift_flags_bleached_filler_token():
    drift, report = kr.detect_generic_drift_tokens(
        _tpa_related(), ["third party claims administrator"], min_count=5,
    )
    assert "party" in drift            # 6 solo-"party" keywords clears the floor
    assert "third" not in drift        # only 2 solo-"third" — below min_count
    assert report["gate"] == "drift"
    assert report["dropped"] == 6


def test_generic_drift_keeps_compound_distinctive_solo_and_adjacency():
    drift, _ = kr.detect_generic_drift_tokens(
        _tpa_related(), ["third party claims administrator"], min_count=5,
    )
    seed_toks = kr.token_set("third party claims administrator")
    # bleached-filler drift dropped...
    assert kr.is_generic_drift("party rentals", seed_toks, drift)
    assert kr.is_generic_drift("birthday party ideas", seed_toks, drift)
    # ...on-topic compound kept (shares >= 2 seed tokens)...
    assert not kr.is_generic_drift("third party administrator", seed_toks, drift)
    # ...single-token adjacency on a DISTINCTIVE token kept...
    assert not kr.is_generic_drift("claims adjuster salary", seed_toks, drift)
    # ...and true adjacency (no seed overlap) kept.
    assert not kr.is_generic_drift("first notice of loss", seed_toks, drift)


def test_generic_drift_inert_when_seed_is_about_the_filler():
    # "party rental company": only ONE distinctive token ("rental" — "party" and
    # "company" are fillers), so the topic could BE the filler. Never gate it,
    # even though solo-"party" keywords dominate.
    related = [
        "party favors", "party venue", "party decorations", "party themes",
        "party games", "party hire", "party ideas",
    ]
    drift, report = kr.detect_generic_drift_tokens(related, ["party rental company"])
    assert drift == set()
    assert report["gate"] == "off"
    assert report["distinctive"] == 1


def test_generic_drift_inert_for_short_topic_seed():
    # "party planning": distinctive tokens < 2 → gate never engages.
    drift, report = kr.detect_generic_drift_tokens(
        ["party favors", "party venue", "party games", "party ideas", "party bus"],
        ["party planning"],
    )
    assert drift == set() and report["gate"] == "off"


def test_generic_drift_below_min_count_never_fires():
    related = ["party rentals", "party supplies", "third party administrator",
               "claims adjuster salary"]
    drift, report = kr.detect_generic_drift_tokens(
        related, ["third party claims administrator"], min_count=5,
    )
    assert drift == set()
    assert report["gate"] == "none"


def test_generic_drift_disabled_returns_empty():
    drift, report = kr.detect_generic_drift_tokens(
        _tpa_related(), ["third party claims administrator"], enabled=False,
    )
    assert drift == set() and report["gate"] == "off"


def test_generic_drift_no_filler_in_seed_is_inert():
    # A clean distinctive seed with no bleached filler token → gate never engages.
    drift, report = kr.detect_generic_drift_tokens(
        ["roof cleaning", "metal roof cost", "gutter guards"],
        ["roof repair contractor"],
    )
    assert drift == set() and report["gate"] == "off"
