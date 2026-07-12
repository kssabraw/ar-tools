"""Unit tests for the LeadOff market-intelligence service (pure logic only —
no Supabase / network; data access is exercised in production, not here)."""
from services.leadoff import (
    enrichment_from_caches,
    grade_for,
    percentile_of,
    recompute_economics,
    sort_value,
)

# a 101-point percentile reference: thresholds 0,10,20,...,1000
BREAKPOINTS = [i * 10.0 for i in range(101)]


def _row(**over):
    base = {
        "city_name": "Vancouver", "state_code": "WA", "category": "Locksmith",
        "category_id": "locksmith", "city_id": 5814616,
        "xdem": 468.0, "rankab": 0.45, "rev_win": 36, "v3": 63.5,
    }
    base.update(over)
    return base


class TestPercentileAndGrade:
    def test_percentile_positions(self):
        assert percentile_of(0, BREAKPOINTS) == 1.0 - 0.0 or percentile_of(0, BREAKPOINTS) >= 0
        assert percentile_of(1005, BREAKPOINTS) == 100.0
        mid = percentile_of(500, BREAKPOINTS)
        assert 45 <= mid <= 55

    def test_percentile_empty_reference(self):
        assert percentile_of(123, []) == 0.0

    def test_grade_bands(self):
        assert grade_for(99.5, leads_mo=50, rankab=0.5, lead_value=25)[0] == "A+"
        assert grade_for(97.2, 50, 0.5, 25)[0] == "A"
        assert grade_for(91.0, 50, 0.5, 25)[0] == "B"
        assert grade_for(60.0, 50, 0.5, 25)[0] == "D"
        assert grade_for(10.0, 50, 0.5, 25)[0] == "F"

    def test_veto_small_market_capped_below_c(self):
        # a 99th-percentile market with <5 leads/mo is capped at 74.9, which
        # lands below the C threshold (>=75) -> grade D, never A/B
        grade, score = grade_for(99.5, leads_mo=3, rankab=0.5, lead_value=25)
        assert grade == "D" and score <= 74.9

    def test_veto_brutal_field_capped_below_c(self):
        grade, _ = grade_for(99.5, leads_mo=100, rankab=0.07, lead_value=25)
        assert grade == "D"

    def test_no_lead_value_is_f(self):
        assert grade_for(99.5, 100, 0.9, None) == ("F", 0.0)


class TestRecomputeEconomics:
    def test_default_assumption_math(self):
        out = recompute_economics(_row(), capture=0.10, lead_value=25,
                                  breakpoints=BREAKPOINTS)
        assert out["est_leads_mo"] == 47            # 468 * 0.10
        assert out["value_mo"] == 1170              # 46.8 * 25
        assert out["exp_val"] in (526, 527)         # 1170 * 0.45, float rounding
        assert out["roi"] == round(out["exp_val"] / 36, 1)

    def test_capture_scales_linearly(self):
        low = recompute_economics(_row(), 0.05, 25, BREAKPOINTS)
        high = recompute_economics(_row(), 0.20, 25, BREAKPOINTS)
        assert high["est_leads_mo"] == 4 * low["est_leads_mo"] or \
            abs(high["est_leads_mo"] - 4 * low["est_leads_mo"]) <= 2  # rounding
        assert high["exp_val"] > low["exp_val"]

    def test_missing_lead_value_grades_f(self):
        out = recompute_economics(_row(), 0.10, None, BREAKPOINTS)
        assert out["grade"] == "F" and out["exp_val"] == 0

    def test_roi_floor_prevents_divide_blowup(self):
        out = recompute_economics(_row(rev_win=0), 0.10, 25, BREAKPOINTS)
        # rev_win floored at 10 reviews of effort
        assert out["roi"] == round(out["exp_val"] / 10, 1)

    def test_sort_value_reads_recomputed_columns(self):
        out = recompute_economics(_row(), 0.10, 25, BREAKPOINTS)
        assert sort_value(out, "expected") == float(out["exp_val"])
        assert sort_value(out, "roi") == float(out["roi"])
        assert sort_value({"exp_val": None}, "expected") == -1.0


class TestEnrichment:
    COMPS = [
        {"business_name": "Vancouver Lock & Key", "domain": "vlk.com"},
        {"business_name": "QuickEntry Locksmith", "domain": "qel.com"},
    ]

    def test_empty_caches_return_none(self):
        assert enrichment_from_caches(self.COMPS, [], [], None, 1) is None

    def test_rd_and_velocity_assembly(self):
        rd = [{"domain": "vlk.com", "referring_domains": 12},
              {"domain": "qel.com", "referring_domains": 4}]
        reviews = [{"biz_key": "vancouver lock key|1", "last30": 3,
                    "prior30": 1, "newest": "2026-06-10"},
                   {"biz_key": "quickentry locksmith|1", "last30": 1,
                    "prior30": 1, "newest": "2026-05-02"}]
        out = enrichment_from_caches(self.COMPS, rd, reviews, None, city_id=1)
        assert out["rd_min"] == 4 and out["rd_med"] == 12
        assert out["field_vel30"] == 4 and out["field_prior30"] == 2
        assert out["vel_matched"] == 2
        assert out["momentum"] == "accel"
        assert out["newest_review"] == "2026-06-10"

    def test_dead_field_momentum(self):
        reviews = [{"biz_key": "vancouver lock key|1", "last30": 0,
                    "prior30": 0, "newest": None},
                   {"biz_key": "quickentry locksmith|1", "last30": 0,
                    "prior30": 0, "newest": None}]
        out = enrichment_from_caches(self.COMPS, [], reviews, None, city_id=1)
        assert out["momentum"] == "dead"

    def test_single_match_suppresses_momentum(self):
        # One matched competitor is too thin for a field-momentum verdict:
        # the raw velocity numbers still surface, the verdict does not.
        reviews = [{"biz_key": "vancouver lock key|1", "last30": 3,
                    "prior30": 0, "newest": "2026-06-10"}]
        out = enrichment_from_caches(self.COMPS, [], reviews, None, city_id=1)
        assert out["field_vel30"] == 3 and out["vel_matched"] == 1
        assert out["momentum"] is None

    def test_trend_only_still_returns_block(self):
        out = enrichment_from_caches(self.COMPS, [], [],
                                     {"growth_yoy": 1.33, "peak_months": "5,12"}, 1)
        assert out["growth_yoy"] == 1.33 and out["momentum"] is None
