"""Unit tests for the LeadOff agency cost-to-win ROI (pure core)."""
from services.leadoff_roi import compute_roi, rd_gap_from_enrichment

# Fixed unit costs so the arithmetic is checkable by hand.
COSTS = dict(cost_per_review=10.0, cost_per_link=30.0, content_pages=4.0,
             content_page_cost=5.0, monthly_maintenance=135.0)


class TestComputeRoi:
    def test_monthly_profit_is_value_minus_maintenance(self):
        r = compute_roi(1449, 16, **COSTS)
        assert r["monthly_profit"] == 1449 - 135  # 1314
        assert r["monthly_cost"] == 135

    def test_modelled_cost_omits_links_and_flags_it(self):
        r = compute_roi(1449, 16, **COSTS)  # no rd_gap_true
        # reviews 16×10=160 + content 4×5=20, no links
        assert r["cost_to_win"] == 180
        assert r["roi_links_estimated"] is True
        assert r["roi_confidence"] == "modelled"
        assert r["cost_breakdown"]["links"] == 0

    def test_measured_cost_includes_links(self):
        r = compute_roi(1449, 16, rd_gap_true=50.0, **COSTS)
        # 160 reviews + 20 content + 50×30=1500 links = 1680
        assert r["cost_to_win"] == 1680
        assert r["roi_links_estimated"] is False
        assert r["roi_confidence"] == "measured"
        assert r["cost_breakdown"]["links"] == 1500

    def test_payback_is_one_time_over_monthly_profit(self):
        r = compute_roi(1449, 16, **COSTS)
        # 180 / 1314 ≈ 0.14 months
        assert r["payback_months"] == round(180 / (1449 - 135), 1)

    def test_never_pays_back_when_maintenance_exceeds_value(self):
        r = compute_roi(100, 16, **COSTS)  # value 100 < maintenance 135
        assert r["monthly_profit"] == 100 - 135  # negative, kept for display
        assert r["payback_months"] is None  # never recoups

    def test_zero_value_is_negative_profit_no_payback(self):
        r = compute_roi(0, 0, **COSTS)
        assert r["monthly_profit"] == -135
        assert r["payback_months"] is None

    def test_none_inputs_degrade_gracefully(self):
        r = compute_roi(None, None, **COSTS)
        # only content (4×5=20) since reviews_n=0
        assert r["cost_to_win"] == 20
        assert r["monthly_profit"] == -135

    def test_higher_review_gap_lengthens_payback(self):
        easy = compute_roi(1449, 5, **COSTS)
        hard = compute_roi(1449, 200, **COSTS)
        assert hard["cost_to_win"] > easy["cost_to_win"]
        assert hard["payback_months"] > easy["payback_months"]


class TestRdGapFromEnrichment:
    def test_none_when_unscouted(self):
        assert rd_gap_from_enrichment(None) is None
        assert rd_gap_from_enrichment({"rd_med": None}) is None

    def test_converts_tool_read_to_true_rd(self):
        # rd_med is a ×10 tool read; gap = rd_med×10×mult
        assert rd_gap_from_enrichment({"rd_med": 5}, mult=1.0) == 50.0
        assert rd_gap_from_enrichment({"rd_med": 5}, mult=1.5) == 75.0

    def test_never_negative(self):
        assert rd_gap_from_enrichment({"rd_med": 0}, mult=1.0) == 0.0
