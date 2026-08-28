"""Unit tests for the LeadOff agency cost-to-win ROI (pure core)."""
from services.leadoff_roi import (
    compute_roi,
    estimate_maintenance,
    estimate_ramp_months,
    field_review_growth,
    rd_gap_from_enrichment,
)

RAMP = dict(ramp_min=3.0, ramp_max=9.0, accel_mult=1.35, cooling_mult=1.05)

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

    def test_payback_without_ramp_is_deliverables_over_profit(self):
        r = compute_roi(1449, 16, **COSTS)  # ramp_months defaults to 0
        # 180 / 1314 ≈ 0.14 months (the unrealistic instant-rank case)
        assert r["payback_months"] == round(180 / (1449 - 135), 1)
        assert r["cost_to_win"] == 180  # ramp 0 ⇒ cost_to_win == deliverables

    def test_first_month_multiplier_adds_a_setup_surcharge(self):
        # 2× first month = one extra month of maintenance on top of the ramp.
        base = compute_roi(1449, 16, ramp_months=4, **COSTS)
        setup = compute_roi(1449, 16, ramp_months=4, first_month_multiplier=2,
                            **COSTS)
        # surcharge = (2−1) × 135 = 135
        assert setup["cost_breakdown"]["setup"] == 135
        assert setup["cost_to_win"] == base["cost_to_win"] + 135
        assert setup["payback_months"] > base["payback_months"]

    def test_first_month_multiplier_default_is_no_surcharge(self):
        r = compute_roi(1449, 16, ramp_months=4, **COSTS)  # default mult 1.0
        assert r["cost_breakdown"]["setup"] == 0

    def test_ramp_makes_payback_realistic(self):
        # 4 months of ramp labour before the ranking arrives.
        r = compute_roi(1449, 16, ramp_months=4, **COSTS)
        # deliverables 180 + ramp 4×135=540 = 720 sunk; profit 1314
        assert r["cost_to_win"] == 720
        assert r["ramp_months"] == 4
        assert r["cost_breakdown"]["ramp"] == 540
        assert r["cost_breakdown"]["deliverables"] == 180
        # payback = ramp + sunk/profit = 4 + 720/1314 ≈ 4.5 months
        assert r["payback_months"] == round(4 + 720 / 1314, 1)
        assert r["payback_months"] > 4  # never the sub-month nonsense

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


class TestEstimateRampMonths:
    def test_soft_field_ramps_near_the_floor(self):
        # Beatability 90 (soft) → ease .9 → 9 - .9×6 = 3.6
        assert estimate_ramp_months(beatability=90, rankab=None, momentum=None,
                                    **RAMP) == 3.6

    def test_brutal_field_ramps_near_the_ceiling(self):
        # Beatability 10 (brutal) → ease .1 → 9 - .1×6 = 8.4
        assert estimate_ramp_months(beatability=10, rankab=None, momentum=None,
                                    **RAMP) == 8.4

    def test_beatability_preferred_over_rankab(self):
        # both present → beatability wins
        r = estimate_ramp_months(beatability=90, rankab=0.1, momentum=None, **RAMP)
        assert r == 3.6

    def test_rankab_fallback_when_no_beatability(self):
        # rankab .75 → ease .75 → 9 - .75×6 = 4.5
        assert estimate_ramp_months(beatability=None, rankab=0.75, momentum=None,
                                    **RAMP) == 4.5

    def test_neither_signal_uses_midpoint_ease(self):
        # ease .5 → 9 - .5×6 = 6.0
        assert estimate_ramp_months(beatability=None, rankab=None, momentum=None,
                                    **RAMP) == 6.0

    def test_accelerating_field_extends_ramp_most(self):
        base = estimate_ramp_months(beatability=50, rankab=None, momentum=None, **RAMP)
        accel = estimate_ramp_months(beatability=50, rankab=None, momentum="accel", **RAMP)
        assert accel == round(base * 1.35, 1)
        assert accel > base  # chasing a moving target takes longer

    def test_cooling_field_still_extends_ramp_slightly(self):
        base = estimate_ramp_months(beatability=50, rankab=None, momentum=None, **RAMP)
        for m in ("cooling", "dead"):
            r = estimate_ramp_months(beatability=50, rankab=None, momentum=m, **RAMP)
            assert r == round(base * 1.05, 1)
            assert r > base  # even a cooling field is still doing some SEO


MAINT = dict(maint_min=135.0, maint_max=400.0)


class TestEstimateMaintenance:
    def test_soft_field_costs_near_the_floor(self):
        # Beatability 90 → ease .9 → 135 + .1×265 = 161.5 → 162
        assert estimate_maintenance(beatability=90, rankab=None, **MAINT) == 162

    def test_brutal_field_costs_near_the_ceiling(self):
        # Beatability 10 → ease .1 → 135 + .9×265 = 373.5 → 374
        assert estimate_maintenance(beatability=10, rankab=None, **MAINT) == 374

    def test_rankab_fallback_and_midpoint(self):
        # no beatability, rankab .5 → ease .5 → 135 + .5×265 = 267.5 → 268
        assert estimate_maintenance(beatability=None, rankab=0.5, **MAINT) == 268
        # neither → midpoint ease .5 → same
        assert estimate_maintenance(beatability=None, rankab=None, **MAINT) == 268

    def test_harder_field_costs_more(self):
        soft = estimate_maintenance(beatability=80, rankab=None, **MAINT)
        hard = estimate_maintenance(beatability=20, rankab=None, **MAINT)
        assert hard > soft


class TestGapGrowth:
    def test_review_growth_inflates_the_review_count(self):
        base = compute_roi(1449, 16, ramp_months=4, **COSTS)
        grown = compute_roi(1449, 16, ramp_months=4,
                            review_growth_per_month=2.0, **COSTS)
        # 16 + 2×4 = 24 effective reviews; growth = 8 reviews = $80
        assert grown["cost_breakdown"]["reviews_n"] == 24
        assert grown["cost_breakdown"]["reviews_growth"] == 8
        assert grown["cost_breakdown"]["reviews"] == base["cost_breakdown"]["reviews"] + 80

    def test_rd_growth_only_applies_when_rd_gap_present(self):
        # modelled (no rd_gap) → no RD, no RD growth
        modelled = compute_roi(1449, 16, ramp_months=4,
                              rd_growth_pct_month=0.03, **COSTS)
        assert modelled["cost_breakdown"]["links_rd"] == 0
        assert modelled["cost_breakdown"]["links_growth"] == 0
        # measured (rd_gap 50) → 50 × (1 + .03×4) = 56 effective RD
        measured = compute_roi(1449, 16, ramp_months=4, rd_gap_true=50.0,
                              rd_growth_pct_month=0.03, **COSTS)
        assert measured["cost_breakdown"]["links_rd"] == 56
        assert measured["cost_breakdown"]["links_growth"] == 6

    def test_no_growth_defaults_are_back_compat(self):
        r = compute_roi(1449, 16, ramp_months=4, rd_gap_true=50.0, **COSTS)
        assert r["cost_breakdown"]["reviews_growth"] == 0
        assert r["cost_breakdown"]["links_growth"] == 0
        assert r["cost_breakdown"]["links_rd"] == 50  # static


class TestFieldReviewGrowth:
    def test_measured_velocity_is_per_competitor_monthly_gain(self):
        # 12 reviews across 4 matched competitors in 30 days → 3/competitor/mo
        assert field_review_growth({"field_vel30": 12, "vel_matched": 4},
                                   default=2.0) == 3.0

    def test_board_wide_falls_back_to_default(self):
        assert field_review_growth(None, default=2.0) == 2.0
        assert field_review_growth({"field_vel30": None, "vel_matched": None},
                                   default=2.5) == 2.5
        # matched 0 → avoid div-by-zero, use default
        assert field_review_growth({"field_vel30": 5, "vel_matched": 0},
                                   default=2.0) == 2.0


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
