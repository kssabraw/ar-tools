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

W = {"prox": 0.10, "site": 0.08, "brand": 0.08, "permit": 0.06, "season": 0.05,
     "peer": 0.07}
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

    def test_peer_field_shifts_winnability(self):
        # field weaker than comparable cities (+1) → more winnable
        assert round(winnability_factor(None, None, None, W, peer_field=1.0), 3) == 1.07
        # field stronger than peers (−1) → less winnable
        assert round(winnability_factor(None, None, None, W, peer_field=-1.0), 3) == 0.93
        # absent → neutral, and it composes with the other winnability signals
        assert winnability_factor(1.0, 0.0, 0.0, W, peer_field=None) == 1.10
        assert round(winnability_factor(1.0, 0.0, 0.0, W, peer_field=1.0), 3) == 1.17

    def test_peer_field_flows_through_enrich_grade(self):
        row = base_row(rankab=0.5, xdem=1000, rev_win=20, exp_val=2500)
        soft = enrich_grade(row, {"peer_field": 1.0}, capture=0.1, lead_value=50,
                            breakpoints=BP, w=W)
        hard = enrich_grade(row, {"peer_field": -1.0}, capture=0.1, lead_value=50,
                            breakpoints=BP, w=W)
        assert soft["rankab"] > 0.5 > hard["rankab"]
        assert soft["exp_val"] > hard["exp_val"]
        assert soft["score_factors"]["signals"].get("peer_field") == 1.0


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

    def test_v3_opportunity_folds_in_the_enrichment(self):
        # the gem ranking (opportunity_v3) must respond to the four signals, not
        # just the grade — v3 × winnability × demand, base_v3 preserved.
        row = {**base_row(rankab=0.5, xdem=1000, rev_win=20), "v3": 60.0}
        tailwind = enrich_grade(
            row, {"proximity": 1.0, "permit": 1.0, "seasonal": 1.0},
            capture=0.1, lead_value=50, breakpoints=BP, w=W)
        headwind = enrich_grade(
            row, {"site_pressure": 1.0, "brand_pressure": 1.0,
                  "permit": -1.0, "seasonal": -1.0},
            capture=0.1, lead_value=50, breakpoints=BP, w=W)
        assert tailwind["base_v3"] == 60.0 and headwind["base_v3"] == 60.0
        # wf=1.10, df=1.11 → 60*1.10*1.11 = 73.3 ; strong tailwind lifts the gem
        assert tailwind["opportunity_v3"] > 60.0
        # site+brand headwind + falling demand sinks it below raw v3
        assert headwind["opportunity_v3"] < 60.0
        # and a market with tailwinds outranks the same market with headwinds
        assert tailwind["opportunity_v3"] > headwind["opportunity_v3"]

    def test_v3_opportunity_defaults_to_zero_without_v3(self):
        out = enrich_grade(base_row(), {"permit": 1.0}, capture=0.1,
                           lead_value=50, breakpoints=BP, w=W)
        assert out["base_v3"] == 0.0 and out["opportunity_v3"] == 0.0

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
                    "permit", "seasonal", "peer_field"))

    def test_peer_field_passthrough(self):
        s = brief_signals({}, [], proximity_opportunity=None,
                          growth_yoy_ss=None, peer_field=0.4)
        assert s["peer_field"] == 0.4
