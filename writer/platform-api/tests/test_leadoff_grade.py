"""Unit tests for the LeadOff on-demand grader's pure logic (no Supabase, no
DataForSEO). The live single-cell path reuses leadoff_actions' tested economics
(tryout_rows) + DataForSEO plumbing, so only the grader-specific helpers are
exercised here."""
from services.leadoff_grade import (
    build_grade_row,
    cache_key,
    grade_market_comps,
    resolve_cpl,
    resolve_service,
    scoutable,
    thin_demand,
)

BOARD = [
    "Roofing contractor", "Plumber", "Water damage restoration service",
    "Air duct cleaning service", "Electrician", "Swimming pool contractor",
]
# 101-point reference: thresholds 0,10,…,1000 (same shape as the live table)
BREAKPOINTS = [i * 10.0 for i in range(101)]


def _field(supply=8, avg5=40, rev_win=25, rating=4.6, namekw=1, holders=2):
    return {"supply": supply, "avg5": avg5, "rev_win": rev_win,
            "rating": rating, "namekw": namekw, "holders": holders}


class TestResolveService:
    def test_exact_catalog_match_keeps_literal_keyword(self):
        # keyword is ALWAYS the literal input; category_name is the catalog match
        r = resolve_service("Plumber", BOARD)
        assert r == {"keyword": "Plumber", "category_name": "Plumber", "on_catalog": True}

    def test_fuzzy_trade_word_grades_literal_but_matches_catalog(self):
        # "roofer" → graded as "roofer", CPL/board from "Roofing contractor"
        r = resolve_service("roofer", BOARD)
        assert r["keyword"] == "roofer"                    # the LITERAL term graded
        assert r["category_name"] == "Roofing contractor"  # catalog match (CPL/board)
        assert r["on_catalog"] is True

    def test_off_catalog_service_grades_literal_no_match(self):
        # nothing overlaps → graded live as the typed term, no catalog category
        r = resolve_service("dumpster rental", BOARD)
        assert r == {"keyword": "dumpster rental", "category_name": None,
                     "on_catalog": False}

    def test_carpenter_is_off_catalog(self):
        r = resolve_service("carpenter", BOARD)
        assert r["on_catalog"] is False
        assert r["keyword"] == "carpenter"
        assert r["category_name"] is None

    def test_whitespace_normalized(self):
        r = resolve_service("  dumpster   rental  ", BOARD)
        assert r["keyword"] == "dumpster rental"

    def test_empty_service(self):
        r = resolve_service("   ", BOARD)
        assert r == {"keyword": "", "category_name": None, "on_catalog": False}


class TestCacheKey:
    def test_city_plus_normalized_name(self):
        assert cache_key(123, "Roofing contractor") == "123|roofing contractor"

    def test_case_and_punct_insensitive(self):
        assert cache_key(5, "Roofing Contractor!") == cache_key(5, "roofing contractor")


class TestResolveCpl:
    LV = {"Roofing contractor": 75.0, "Plumber": 50.0}

    def test_exact_hit(self):
        assert resolve_cpl("Roofing contractor", self.LV, 50.0) == (75.0, False)

    def test_case_insensitive_hit(self):
        assert resolve_cpl("roofing contractor", self.LV, 50.0) == (75.0, False)

    def test_off_catalog_uses_default_flagged(self):
        assert resolve_cpl("dumpster rental", self.LV, 50.0) == (50.0, True)


class TestThinDemand:
    def test_below_gate_is_thin(self):
        assert thin_demand(10) is True

    def test_at_gate_not_thin(self):
        assert thin_demand(20) is False

    def test_above_gate_not_thin(self):
        assert thin_demand(140) is False

    def test_none_not_thin(self):
        assert thin_demand(None) is False


class TestBuildGradeRow:
    def test_composes_grade_and_tags(self):
        # the literal keyword "roofer" is graded; the CPL/holders came from the
        # catalog category, recorded as lead_category
        row = build_grade_row(
            keyword="roofer", category_id="roofing_contractor",
            lead_category="Roofing contractor",
            vol=300, cpc=12.0, field=_field(), cpl=75.0, cpl_default=False,
            breakpoints=BREAKPOINTS, capture=0.10,
            competitors=[{"business_name": "ACME Roofing"}])
        assert row["category"] == "roofer"                 # the literal keyword graded
        assert row["lead_category"] == "Roofing contractor"  # CPL/holder source
        assert row["category_id"] == "roofing_contractor"
        assert "grade" in row and "exp_val" in row
        assert row["exp_val"] > 0                    # real demand + value → graded
        assert row["thin_demand"] is False
        assert row["cpl"] == 75.0 and row["cpl_default"] is False   # default mult 1.0
        assert row["cpl_modifier"] == 1.0 and row["cpl_base"] == 75.0
        assert row["competitors"] == [{"business_name": "ACME Roofing"}]

    def test_cpc_modifier_applies_to_the_grade(self):
        base = build_grade_row(
            keyword="roofer", category_id="roofing_contractor",
            lead_category="Roofing contractor", vol=300, cpc=30.0,
            field=_field(), cpl=100.0, cpl_default=False,
            breakpoints=BREAKPOINTS, capture=0.10)
        hot = build_grade_row(
            keyword="roofer", category_id="roofing_contractor",
            lead_category="Roofing contractor", vol=300, cpc=45.0,
            field=_field(), cpl=100.0, cpl_default=False,
            breakpoints=BREAKPOINTS, capture=0.10, cpl_multiplier=1.4)
        assert hot["cpl"] == 140.0 and hot["cpl_base"] == 100.0
        assert hot["exp_val"] > base["exp_val"]   # a hotter ad-market grades higher

    def test_thin_demand_market_still_grades(self):
        # the whole point of on-demand: a below-gate cell is graded, not withheld
        row = build_grade_row(
            keyword="dryer vent cleaning", category_id=None, lead_category=None,
            vol=10, cpc=3.0, field=_field(), cpl=40.0, cpl_default=True,
            breakpoints=BREAKPOINTS, capture=0.10)
        assert row["thin_demand"] is True
        assert row["cpl_default"] is True
        assert row["category_id"] is None
        assert row["lead_category"] is None
        assert "grade" in row                        # a grade was still produced


def _grade_row(**over):
    row = {"status": "complete", "on_catalog": True, "category_id": "plumber",
           "city_id": 5368304, "category_name": "Plumber",
           "city_name": "Los Alamitos", "state_code": "CA",
           "grade": {"grade": "B", "competitors": [
               {"business_name": "ACME Plumbing", "domain": "acme.com", "phone": "1"},
               {"business_name": "Bob Pipes", "domain": "bob.com", "phone": "2"}]}}
    row.update(over)
    return row


class TestScoutable:
    def test_on_catalog_complete_with_comps_is_scoutable(self):
        assert scoutable(_grade_row()) is None

    def test_incomplete_grade_not_scoutable(self):
        assert scoutable(_grade_row(status="running")) == "grade_not_ready"

    def test_off_catalog_not_scoutable(self):
        # scout keys on a real category_id — a free-text service has none
        assert scoutable(_grade_row(on_catalog=False, category_id=None)) == "scout_requires_catalog"

    def test_on_catalog_but_no_category_id_not_scoutable(self):
        assert scoutable(_grade_row(category_id=None)) == "scout_requires_catalog"

    def test_no_competitors_not_scoutable(self):
        assert scoutable(_grade_row(grade={"grade": "B", "competitors": []})) == "no_competitors"


class TestGradeMarketComps:
    def test_builds_market_and_ranked_comps(self):
        market, comps = grade_market_comps(_grade_row())
        assert market == {"city_id": 5368304, "category_id": "plumber",
                          "category": "Plumber", "city_name": "Los Alamitos",
                          "state_code": "CA"}
        assert [c["rank_position"] for c in comps] == [1, 2]
        assert comps[0]["business_name"] == "ACME Plumbing"
        assert comps[0]["domain"] == "acme.com"

    def test_empty_competitors_yield_empty_list(self):
        _market, comps = grade_market_comps(_grade_row(grade={"competitors": []}))
        assert comps == []

    def test_scout_uses_lead_category_over_literal_keyword(self):
        # a literal-keyword grade ("roofer") scouts against its catalog category
        # (the scanner's Pass-2 caches are keyed by category, not the keyword)
        row = _grade_row(category_name="roofer", category_id="roofing_contractor",
                         grade={"lead_category": "Roofing contractor", "grade": "B",
                                "competitors": [{"business_name": "ACME"}]})
        market, _comps = grade_market_comps(row)
        assert market["category"] == "Roofing contractor"

    def test_scout_falls_back_to_category_name_without_lead_category(self):
        # older rows carry no lead_category → the stored category_name is used
        market, _comps = grade_market_comps(_grade_row())
        assert market["category"] == "Plumber"
