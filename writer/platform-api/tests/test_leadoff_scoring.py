"""Unit tests for the LeadOff score-enrichment engine (pure)."""
from services.leadoff_scoring import (
    brand_pressure,
    brief_signals,
    demand_factor,
    enrich_grade,
    permit_signal,
    seasonal_signal,
    site_pressure,
    winnability_factor,
)

W = {"prox": 0.10, "site": 0.08, "brand": 0.08, "permit": 0.06, "season": 0.05}
# a coarse breakpoint reference (0..1000 in 100-point steps)
BP = list(range(0, 1001, 10))


def base_row(rankab=0.5, xdem=1000, rev_win=20, grade="C", exp_val=300):
    return {"rankab": rankab, "xdem": xdem, "rev_win": rev_win,
            "grade": grade, "exp_val": exp_val, "category": "plumber"}


class TestNormalizers:
    def test_site_pressure_log_curve(self):
        assert site_pressure(1000) == 1.0
        assert round(site_pressure(100), 2) == 0.67
        assert site_pressure(None) == 0.0 and site_pressure(0) == 0.0
        assert site_pressure(10_000) == 1.0  # clamped

    def test_brand_pressure_log_curve(self):
        assert brand_pressure(10_000) == 1.0
        assert 0.78 <= brand_pressure(1478) <= 0.80   # Saela
        assert brand_pressure(None) == 0.0

    def test_permit_signal(self):
        assert permit_signal("HOT-pipeline") == 1.0
        assert permit_signal("COLD-pipeline") == -1.0
        assert permit_signal("-") == 0.0 and permit_signal(None) == 0.0

    def test_seasonal_signal(self):
        assert seasonal_signal(1.0) == 0.0
        assert seasonal_signal(1.5) == 1.0     # +50% → full tailwind
        assert seasonal_signal(0.5) == -1.0
        assert seasonal_signal(3.0) == 1.0     # clamped
        assert seasonal_signal(None) == 0.0


class TestFactors:
    def test_winnability_swings_bounded(self):
        # best case: undefended + weak incumbents
        assert winnability_factor(1.0, 0.0, 0.0, W) == 1.10
        # worst case: no opening + huge incumbents
        assert round(winnability_factor(0.0, 1.0, 1.0, W), 3) == 0.84
        # absent signals → neutral
        assert winnability_factor(None, None, None, W) == 1.0

    def test_demand_factor(self):
        assert round(demand_factor(1.0, 1.0, W), 3) == 1.11      # HOT + rising
        assert round(demand_factor(-1.0, -1.0, W), 3) == 0.89
        assert demand_factor(None, None, W) == 1.0


class TestEnrichGrade:
    def test_no_signals_is_a_noop_on_economics(self):
        row = base_row(rankab=0.5, xdem=1000, rev_win=20)
        out = enrich_grade(row, {}, capture=0.1, lead_value=50, breakpoints=BP, w=W)
        # base exp_val = round(1000*0.1*50 * 0.5) = 2500 → but clamp of grade aside,
        # the point: factors are 1.0 so rankab/xdem unchanged
        assert out["score_factors"]["winnability"] == 1.0
        assert out["score_factors"]["demand"] == 1.0
        assert out["rankab"] == 0.5 and out["xdem"] == 1000
        assert out["enriched"] is False

    def test_positive_signals_raise_expected_value(self):
        row = base_row(rankab=0.5, xdem=1000, rev_win=20, exp_val=2500)
        signals = {"proximity": 1.0, "site_pressure": 0.0, "brand_pressure": 0.0,
                   "permit": 1.0, "seasonal": 1.0}
        out = enrich_grade(row, signals, capture=0.1, lead_value=50,
                           breakpoints=BP, w=W)
        # rankab ×1.10, xdem ×1.11 → exp_val strictly above base
        assert out["rankab"] == 0.55
        assert out["xdem"] == 1110
        # base recomputed at the same assumptions = 1000*0.1*50*0.5 = 2500
        assert out["base_exp_val"] == 2500 and out["base_rankab"] == 0.5
        assert out["exp_val"] > out["base_exp_val"]
        assert out["enriched"] is True

    def test_negative_signals_lower_expected_value(self):
        row = base_row(rankab=0.5, xdem=1000, rev_win=20, exp_val=2500)
        signals = {"proximity": 0.0, "site_pressure": 1.0, "brand_pressure": 1.0,
                   "permit": -1.0, "seasonal": -1.0}
        out = enrich_grade(row, signals, capture=0.1, lead_value=50,
                           breakpoints=BP, w=W)
        assert out["rankab"] < 0.5 and out["xdem"] < 1000
        assert out["exp_val"] < 2500

    def test_rankab_clamped(self):
        row = base_row(rankab=0.99)
        signals = {"proximity": 1.0}  # would push >1
        out = enrich_grade(row, signals, capture=0.1, lead_value=50,
                           breakpoints=BP, w={"prox": 0.5, "site": 0, "brand": 0,
                                              "permit": 0, "season": 0})
        assert out["rankab"] <= 1.0

    def test_no_lead_value_is_F(self):
        out = enrich_grade(base_row(), {"permit": 1.0}, capture=0.1,
                           lead_value=None, breakpoints=BP, w=W)
        assert out["grade"] == "F"


class TestBriefSignals:
    def test_medians_and_flags(self):
        row = {"permit_flag": "HOT-pipeline"}
        comps = [{"site_pages": 100, "mentions": 1478},
                 {"site_pages": 1000, "mentions": None},
                 {"site_pages": None, "mentions": 500}]
        s = brief_signals(row, comps, proximity_opportunity=0.6, growth_yoy_ss=1.2)
        assert s["proximity"] == 0.6
        # site median of [100,1000] = 550 → pressure ~0.91
        assert 0.88 <= s["site_pressure"] <= 0.92
        # mention median of [500,1478] = 989 → ~0.75
        assert 0.70 <= s["brand_pressure"] <= 0.78
        assert s["permit"] == 1.0
        assert round(s["seasonal"], 2) == 0.40   # (1.2-1)*2

    def test_absent_pieces_are_none(self):
        s = brief_signals({}, [{"site_pages": None, "mentions": None}],
                          proximity_opportunity=None, growth_yoy_ss=None)
        assert all(s[k] is None for k in
                   ("proximity", "site_pressure", "brand_pressure",
                    "permit", "seasonal"))
