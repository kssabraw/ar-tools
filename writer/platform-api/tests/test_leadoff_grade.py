"""Unit tests for the LeadOff on-demand grader's pure logic (no Supabase, no
DataForSEO). The live single-cell path reuses leadoff_actions' tested economics
(tryout_rows) + DataForSEO plumbing, so only the grader-specific helpers are
exercised here."""
from services.leadoff_grade import (
    build_grade_row,
    cache_key,
    resolve_cpl,
    resolve_service,
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
    def test_exact_catalog_match_is_on_catalog(self):
        r = resolve_service("Plumber", BOARD)
        assert r == {"category_name": "Plumber", "on_catalog": True}

    def test_fuzzy_trade_word_resolves_on_catalog(self):
        # "roofing" → "Roofing contractor" (stemmed roof↔roofing)
        r = resolve_service("roofing", BOARD)
        assert r["on_catalog"] is True
        assert r["category_name"] == "Roofing contractor"

    def test_off_catalog_service_kept_verbatim(self):
        # nothing overlaps → graded live as the typed service
        r = resolve_service("dumpster rental", BOARD)
        assert r == {"category_name": "dumpster rental", "on_catalog": False}

    def test_carpenter_is_off_catalog(self):
        r = resolve_service("carpenter", BOARD)
        assert r["on_catalog"] is False
        assert r["category_name"] == "carpenter"

    def test_whitespace_normalized(self):
        r = resolve_service("  dumpster   rental  ", BOARD)
        assert r["category_name"] == "dumpster rental"

    def test_empty_service(self):
        r = resolve_service("   ", BOARD)
        assert r == {"category_name": "", "on_catalog": False}


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
        row = build_grade_row(
            category_name="Roofing contractor", category_id="roofing_contractor",
            vol=300, cpc=12.0, field=_field(), cpl=75.0, cpl_default=False,
            breakpoints=BREAKPOINTS, capture=0.10,
            competitors=[{"business_name": "ACME Roofing"}])
        assert row["category"] == "Roofing contractor"
        assert row["category_id"] == "roofing_contractor"
        assert "grade" in row and "exp_val" in row
        assert row["exp_val"] > 0                    # real demand + value → graded
        assert row["thin_demand"] is False
        assert row["cpl"] == 75.0 and row["cpl_default"] is False
        assert row["competitors"] == [{"business_name": "ACME Roofing"}]

    def test_thin_demand_market_still_grades(self):
        # the whole point of on-demand: a below-gate cell is graded, not withheld
        row = build_grade_row(
            category_name="Dryer vent cleaning service", category_id=None,
            vol=10, cpc=3.0, field=_field(), cpl=40.0, cpl_default=True,
            breakpoints=BREAKPOINTS, capture=0.10)
        assert row["thin_demand"] is True
        assert row["cpl_default"] is True
        assert row["category_id"] is None
        assert "grade" in row                        # a grade was still produced
