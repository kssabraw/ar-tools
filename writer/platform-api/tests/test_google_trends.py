"""Unit tests for the Google Trends Discovery module's pure logic (no I/O).

The DataForSEO explore response shape is verified against docs but NOT a live
call (the build sandbox is egress-blocked); these fixtures encode the documented
shape. scripts/verify_google_trends.py confirms it live from Railway before the
flag flips — if the live shape differs, update parse_rising_queries AND these
fixtures together.
"""

from services import google_trends as g


# --- parse_rising_value -------------------------------------------------------
def test_parse_rising_value_breakout():
    assert g.parse_rising_value("Breakout") == (g._BREAKOUT_PCT, True)
    assert g.parse_rising_value("breakout") == (g._BREAKOUT_PCT, True)


def test_parse_rising_value_percent_forms():
    assert g.parse_rising_value("+250%") == (250.0, False)
    assert g.parse_rising_value("1,200") == (1200.0, False)
    assert g.parse_rising_value(80) == (80.0, False)
    assert g.parse_rising_value(80.5) == (80.5, False)


def test_parse_rising_value_junk_and_negative():
    assert g.parse_rising_value("n/a") == (0.0, False)
    assert g.parse_rising_value(None) == (0.0, False)
    assert g.parse_rising_value(-40) == (0.0, False)  # clamped


# --- velocity_factor (monotonic, bounded) -------------------------------------
def test_velocity_factor_monotonic_and_anchored():
    assert g.velocity_factor(0) == 1.0
    assert g.velocity_factor(0) < g.velocity_factor(100) < g.velocity_factor(5000)
    # bounded — a breakout doesn't swamp the demand signal it multiplies
    assert g.velocity_factor(g._BREAKOUT_PCT) < 3.0


# --- trend_score (reuses the existing opportunity model) ----------------------
def test_trend_score_zero_when_no_commercial_demand():
    # opportunity_score is value(volume*cpc) × ease × intent → 0 when cpc is 0,
    # so a high-velocity but commercially-empty query scores 0 (by design).
    assert g.trend_score(g._BREAKOUT_PCT, 100000, 0.0, 10, "commercial") == 0.0
    assert g.trend_score(500, None, None, None, None) == 0.0


def test_trend_score_rises_with_velocity_and_demand():
    low = g.trend_score(100, 1000, 2.0, 20, "commercial")
    high = g.trend_score(5000, 1000, 2.0, 20, "commercial")
    assert high > low > 0
    # more demand → higher score at equal velocity
    assert g.trend_score(500, 5000, 2.0, 20, "commercial") > g.trend_score(500, 1000, 2.0, 20, "commercial")


# --- parse_rising_queries (defensive) -----------------------------------------
def _explore_body(rising, top=None):
    data = {"rising": rising}
    if top is not None:
        data["top"] = top
    return {"tasks": [{"result": [{"items": [
        {"type": "google_trends_graph", "data": {}},
        {"type": "google_trends_queries_list", "data": data},
    ]}]}]}


def test_parse_rising_queries_extracts_rising_only_by_default():
    body = _explore_body(
        rising=[{"query": "bpc 157 dosage", "value": "Breakout"},
                {"query": "tb500 stack", "value": 300}],
        top=[{"query": "peptides", "value": 100}],
    )
    out = g.parse_rising_queries(body)
    queries = [r["query"] for r in out]
    assert queries == ["bpc 157 dosage", "tb500 stack"]  # top excluded by default
    assert out[0]["is_breakout"] is True
    assert out[0]["rising_value"] == g._BREAKOUT_PCT
    assert out[1]["rising_value"] == 300.0
    assert all(r["bucket"] == "rising" for r in out)


def test_parse_rising_queries_include_top():
    body = _explore_body(rising=[{"query": "a", "value": 10}], top=[{"query": "b", "value": 5}])
    out = g.parse_rising_queries(body, include_top=True)
    assert {r["query"] for r in out} == {"a", "b"}
    assert next(r for r in out if r["query"] == "b")["bucket"] == "top"


def test_parse_rising_queries_dedupes_normalized():
    body = _explore_body(rising=[{"query": "BPC 157", "value": 100},
                                 {"query": "bpc  157", "value": 200}])
    out = g.parse_rising_queries(body)
    assert len(out) == 1  # normalized dedupe (case + whitespace)


def test_parse_rising_queries_defensive_on_junk():
    assert g.parse_rising_queries({}) == []
    assert g.parse_rising_queries({"tasks": None}) == []
    assert g.parse_rising_queries({"tasks": [{"result": [{"items": [
        {"type": "google_trends_queries_list", "data": {"rising": [
            {"value": 100},            # no query
            {"query": "", "value": 1}, # empty query
            "notadict",
        ]}},
    ]}]}]}) == []


# --- build_trend_rows ---------------------------------------------------------
def test_build_trend_rows_qualified_flag_and_sort():
    rising = [
        {"query": "cheap widget", "bucket": "rising", "rising_value": 5000, "is_breakout": True},
        {"query": "premium widget kit", "bucket": "rising", "rising_value": 300, "is_breakout": False},
        {"query": "no demand term", "bucket": "rising", "rising_value": 800, "is_breakout": False},
    ]
    overview = {
        "cheap widget": {"volume": 200, "cpc_usd": 0.0, "keyword_difficulty": 10, "search_intent": "commercial"},
        "premium widget kit": {"volume": 500, "cpc_usd": 3.0, "keyword_difficulty": 25, "search_intent": "transactional"},
        # "no demand term" absent → unqualified
    }
    rows = g.build_trend_rows(rising, overview)
    by_q = {r["query"]: r for r in rows}
    assert by_q["premium widget kit"]["qualified"] is True
    assert by_q["cheap widget"]["qualified"] is True        # has volume even though cpc 0
    assert by_q["no demand term"]["qualified"] is False     # no overview row
    # premium (real cpc) outranks cheap (cpc 0 → score 0) outranks no-demand
    assert rows[0]["query"] == "premium widget kit"
    # sorted by trend_score desc then volume
    scores = [r["trend_score"] or 0.0 for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_build_trend_rows_empty():
    assert g.build_trend_rows([], {}) == []


# --- parse_categories (nested) ------------------------------------------------
def test_parse_categories_flattens_tree():
    body = {"tasks": [{"result": [{"items": [
        {"category_code": 0, "category_name": "All categories", "items": [
            {"category_code": 3, "category_name": "Arts & Entertainment", "category_code_parent": 0},
            {"category_code": 5, "category_name": "Computers", "category_code_parent": 0, "items": [
                {"category_code": 30, "category_name": "Software", "category_code_parent": 5},
            ]},
        ]},
    ]}]}]}
    cats = g.parse_categories(body)
    codes = {c["category_code"] for c in cats}
    assert {0, 3, 5, 30} <= codes
    software = next(c for c in cats if c["category_code"] == 30)
    assert software["category_name"] == "Software"
    assert software["parent_code"] == 5


def test_parse_categories_defensive():
    assert g.parse_categories({}) == []
    assert g.parse_categories({"tasks": [{"result": None}]}) == []


# --- Phase 2: derive_category_seeds (site topics + expansion, deduped/capped) --
def test_derive_category_seeds_merges_dedupes_caps():
    tr = {
        "site": {"topics": ["Historic Preservation", "historic  preservation", "Adaptive Reuse"]},
        "expansion_seeds": ["national trust", "Adaptive Reuse"],  # dup of a site topic
    }
    out = g.derive_category_seeds(tr, cap=3)
    # normalized dedupe (case + whitespace), site topics before expansion, capped
    assert out == ["Historic Preservation", "Adaptive Reuse", "national trust"]


def test_derive_category_seeds_empty_when_no_signal():
    assert g.derive_category_seeds({}, cap=5) == []
    assert g.derive_category_seeds({"site": {"topics": []}, "expansion_seeds": []}, cap=5) == []
    # junk entries are skipped
    assert g.derive_category_seeds({"site": {"topics": ["", "   ", 3]}}, cap=5) == []
    assert g.derive_category_seeds(None, cap=5) == []  # non-dict guard


def test_derive_category_seeds_falls_back_to_icp_intents():
    # A client with an ICP but no discoverable website: no site topics, no
    # expansion — the ICP-grounded intents still anchor the scan.
    tr = {"site": {"topics": []}, "expansion_seeds": [],
          "intents": ["reducing claims leakage", "catastrophe surge staffing"]}
    assert g.derive_category_seeds(tr, cap=5) == ["reducing claims leakage", "catastrophe surge staffing"]
    # But site topics lead when present (intents are the fallback, appended last).
    tr2 = {"site": {"topics": ["roof restoration"]}, "expansion_seeds": [],
           "intents": ["storm damage repair"]}
    assert g.derive_category_seeds(tr2, cap=5) == ["roof restoration", "storm damage repair"]


# --- head_term_seeds (broader head terms for the category scan) ---------------
def test_head_term_seeds_shortens_long_tail_phrases():
    seeds = [
        "does semax need to be refrigerated",          # question/filler dropped
        "ajp endocrinology and metabolism impact factor",
        "collagen peptides",                            # already a head term
    ]
    out = g.head_term_seeds(seeds, cap=10)
    # tokenize drops interrogatives ("does") + stopwords ("to", "and"); the first
    # up-to-3 significant tokens are kept as the head term.
    assert out[0] == "semax need be"
    assert out[1] == "ajp endocrinology metabolism"
    assert out[2] == "collagen peptides"


def test_head_term_seeds_drops_question_words():
    # A pure-interrogative lead ("what is") never survives into the head term.
    assert g.head_term_seeds(["what is retatrutide"], cap=5) == ["retatrutide"]
    assert g.head_term_seeds(["how does semaglutide work"], cap=5) == ["semaglutide work"]


def test_head_term_seeds_dedupes_after_shortening():
    # Distinct long-tail phrases sharing the same first-3 head tokens collapse to
    # one head term → deduped (fewer redundant explores).
    out = g.head_term_seeds(
        ["collagen peptides powder", "collagen peptides powder for skin", "marine collagen"],
        cap=10,
    )
    assert out == ["collagen peptides powder", "marine collagen"]


def test_head_term_seeds_caps():
    seeds = [f"term{n} extra words here" for n in range(10)]
    out = g.head_term_seeds(seeds, cap=3)
    assert len(out) == 3
    assert out == ["term0 extra words", "term1 extra words", "term2 extra words"]


def test_head_term_seeds_falls_through_when_all_filler():
    # A seed with no significant tokens left (all stopwords/interrogatives) falls
    # through as-is rather than being dropped (best-effort).
    assert g.head_term_seeds(["how to", "  ", 3, "retatrutide"], cap=5) == ["how to", "retatrutide"]


# --- Phase 3: build_digest_summary (deterministic weekly body) ----------------
def test_build_digest_summary_lines_and_attribution():
    rows = [
        {"query": "collagen gummies", "is_breakout": True, "volume": 12000, "source_client_name": "Acme"},
        {"query": "marine collagen", "is_breakout": False, "rising_value": 250, "volume": 3000, "source_client_name": None},
    ]
    out = g.build_digest_summary(rows, total_qualified=5)
    assert "*2*" in out and "5 qualified" in out
    assert "collagen gummies" in out and "Breakout" in out and "Acme" in out
    assert "marine collagen" in out and "+250%" in out and "3,000/mo" in out


def test_build_digest_summary_empty():
    assert "No qualified" in g.build_digest_summary([], 0)


# --- Phase 4: interest_over_time point parsing --------------------------------
def test_point_month_and_value_shapes():
    from datetime import datetime, timezone
    assert g._point_month({"date_from": "2025-03-15"}) == 3
    assert g._point_month({"month": 7}) == 7
    assert g._point_month({"timestamp": datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()}) == 6
    assert g._point_month({}) is None
    assert g._point_month({"date_from": "junk"}) is None
    assert g._point_value({"value": 42}) == 42.0
    assert g._point_value({"values": [55]}) == 55.0
    assert g._point_value({"values": [{"value": 33}]}) == 33.0
    assert g._point_value({"data": [{"value": 7}]}) == 7.0
    assert g._point_value({}) is None


def _graph_body(points):
    return {"tasks": [{"result": [{"items": [
        {"type": "google_trends_queries_list", "data": {"rising": []}},
        {"type": "google_trends_graph", "data": points},
    ]}]}]}


def test_parse_interest_over_time_extracts_points():
    body = _graph_body([
        {"date_from": "2025-01-01", "values": [50]},
        {"date_from": "2025-02-01", "value": 80},
        {"date_from": "2025-04-01", "values": [90], "missing_data": True},  # gap → dropped
        {"date_from": "junk"},   # no month → dropped
        {"date_from": "2025-03-01"},  # no value → dropped
        "notadict",
    ])
    out = g.parse_interest_over_time(body)
    assert out == [{"month": 1, "value": 50.0}, {"month": 2, "value": 80.0}]


def test_parse_interest_over_time_defensive():
    assert g.parse_interest_over_time({}) == []
    assert g.parse_interest_over_time({"tasks": [{"result": [{"items": [
        {"type": "google_trends_graph", "data": None}]}]}]}) == []


# --- Phase 4: seasonality profile (feeds trend_watch.demand_outlook) ----------
def test_seasonality_profile_needs_six_months():
    series = [{"month": m, "value": 10} for m in range(1, 6)]  # only 5 months
    assert g.seasonality_profile_from_series(series) is None


def test_seasonality_profile_index_normalized_to_mean():
    series = [{"month": m, "value": 200 if m == 12 else 100} for m in range(1, 13)]
    prof = g.seasonality_profile_from_series(series)
    assert prof is not None
    idx = prof["index"]
    assert set(idx) == set(range(1, 13))
    mean = (11 * 100 + 200) / 12
    assert abs(idx[12] - 200 / mean) < 0.01   # 1.0 == the year's mean
    assert abs(idx[1] - 100 / mean) < 0.01
    assert 12 in prof["peak_months"] and 12 not in prof["low_months"]


def test_seasonality_profile_zero_mean_none():
    assert g.seasonality_profile_from_series([{"month": m, "value": 0} for m in range(1, 13)]) is None


def test_seasonal_date_from_is_months_back():
    d = g._seasonal_date_from(24)
    assert len(d) == 10 and d.endswith("-01") and d[4] == "-"


# --- _explore_and_qualify: ONE explore per seed -------------------------------
# Google Trends rising/related queries are single-term: a multi-keyword explore is
# a comparison view with no queries list and returns 0 rising (verified live
# 2026-09-15). So every rising-query scan must explore one keyword per call.
def test_queries_explore_is_single_keyword():
    assert g._QUERIES_EXPLORE_KEYWORDS == 1


async def test_explore_and_qualify_explores_one_seed_per_call(monkeypatch):
    calls: list[list[str]] = []

    async def fake_explore_live(keywords, **kwargs):
        calls.append(list(keywords))
        seed = keywords[0]  # each explore carries one seed; return its own rising query
        return _explore_body([{"query": f"{seed} rising", "value": 120}]), 0.006

    async def fake_overview(queries, **kwargs):
        return {q: {"volume": 1000, "cpc_usd": 1.0, "competition_index": 10,
                    "keyword_difficulty": 5.0, "search_intent": "commercial"}
                for q in queries}, 0.01

    monkeypatch.setattr(g, "explore_live", fake_explore_live)
    monkeypatch.setattr(g, "reserve_budget", lambda n: None)
    monkeypatch.setattr(g.dataforseo_labs, "fetch_keyword_overview", fake_overview)
    monkeypatch.setattr(g.dataforseo_labs, "labs_location_code", lambda c: c)

    rows, cost = await g._explore_and_qualify(
        ["semaglutide", "collagen peptides", "retatrutide"],
        category_code=None, location_code=None, language_code="en", trends_type="web",
    )

    # one explore call per seed, each carrying exactly one keyword
    assert calls == [["semaglutide"], ["collagen peptides"], ["retatrutide"]]
    # every rising query attributes to its exact seed
    by_query = {r["query"]: r["seed"] for r in rows}
    assert by_query["semaglutide rising"] == "semaglutide"
    assert by_query["collagen peptides rising"] == "collagen peptides"
    assert by_query["retatrutide rising"] == "retatrutide"
    assert cost > 0
