"""Unit tests for the LeadOff calibration surface's pure logic (Phase 0 —
plan: docs/modules/leadoff-calibration-plan-v1_0.md, §7 owner rulings)."""
from datetime import datetime, timezone

from services.leadoff_calibration import (
    MAPS_RANKED_SHARE,
    build_outcome,
    frozen_bar,
    horizon_bucket,
    live_bar,
    maps_share,
    match_keyword,
    months_elapsed,
    summarize,
)

NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


def _prediction(**over):
    base = {
        "id": "p1", "client_id": "c1", "category": "Locksmith",
        "city_name": "Vancouver", "state_code": "WA", "as_of": "2026-07",
        "created_at": "2026-01-12T00:00:00+00:00",
        "predicted": {"rev_win": 36, "rankab": 0.45, "exp_leads_mo": 21,
                      "exp_val": 529},
        "competitors": [
            {"rank_position": 1, "business_name": "A", "review_count": 46},
            {"rank_position": 2, "business_name": "B", "review_count": 201},
            {"rank_position": 3, "business_name": "C", "review_count": 10},
            {"rank_position": 4, "business_name": "D", "review_count": 21},
            {"rank_position": 5, "business_name": "E", "review_count": 36},
        ],
    }
    base.update(over)
    return base


class TestBars:
    def test_frozen_bar_is_third_highest(self):
        # counts 46,201,10,21,36 → sorted desc 201,46,36 → bar = 36 (= rev_win)
        assert frozen_bar(_prediction()["competitors"]) == 36

    def test_frozen_bar_small_fields(self):
        assert frozen_bar([{"review_count": 12}]) == 12
        assert frozen_bar([]) is None

    def test_live_bar(self):
        assert live_bar([300, 50, 40, 10]) == 40
        assert live_bar([]) is None


class TestMatching:
    TRACKED = [
        {"id": "k1", "keyword": "locksmith"},
        {"id": "k2", "keyword": "locksmith vancouver"},
        {"id": "k3", "keyword": "plumber vancouver"},
    ]

    def test_prefers_category_plus_city(self):
        assert match_keyword(self.TRACKED, "Locksmith", "Vancouver")["id"] == "k2"

    def test_falls_back_to_category_only(self):
        assert match_keyword(self.TRACKED, "Locksmith", "Bend")["id"] == "k1"

    def test_no_match_is_none(self):
        assert match_keyword(self.TRACKED, "Roofing Contractor", "Vancouver") is None

    def test_maps_share_filters_by_category(self):
        results = [
            {"keyword": "locksmith vancouver", "top3_pins": 30, "total_pins": 49},
            {"keyword": "plumber vancouver", "top3_pins": 49, "total_pins": 49},
        ]
        assert maps_share(results, "Locksmith") == round(100 * 30 / 49, 1)
        assert maps_share(results, "Electrician") is None


class TestOutcome:
    def test_rev_win_outcome_and_drift(self):
        out = build_outcome(_prediction(), {
            "client_reviews": 40,
            "competitor_review_counts": [210, 50, 44, 12],
        }, NOW)
        o = out["outcome"]
        assert o["bar_cleared"] is True          # 40 > frozen bar 36
        assert o["live_bar"] == 44
        assert out["errors"]["bar_drift"] == 44 - 36  # the bar moved +8
        assert out["months_elapsed"] == 5.9  # 181 days / 30.44

    def test_rankab_residual_uses_owner_ruling_bar(self):
        # 49% share is NOT ranked under the ≥50% ruling
        out = build_outcome(_prediction(), {
            "client_reviews": 5, "competitor_review_counts": [],
            "maps_top3_share": 49.9,
        }, NOW)
        assert out["outcome"]["ranked_maps"] is False
        assert out["errors"]["rankab_residual"] == round(0 - 0.45, 2)
        out2 = build_outcome(_prediction(), {
            "client_reviews": 5, "competitor_review_counts": [],
            "maps_top3_share": MAPS_RANKED_SHARE,
        }, NOW)
        assert out2["outcome"]["ranked_maps"] is True
        assert out2["errors"]["rankab_residual"] == round(1 - 0.45, 2)

    def test_coverage_reasons_for_missing_sources(self):
        out = build_outcome(_prediction(), {}, NOW)
        cov = out["coverage"]
        assert "rev_win" in cov            # no client GBP reviews
        assert "rankab_maps" in cov        # no maps scan
        assert "rankab_organic" in cov     # no tracked keyword (manual ruling)
        assert "exp_leads" in cov          # the hard gap, always named
        assert out["errors"] == {}         # nothing computable → nothing faked

    def test_organic_ranked_bar(self):
        out = build_outcome(_prediction(), {
            "client_reviews": 1, "competitor_review_counts": [],
            "organic_position": 8.0,
        }, NOW)
        assert out["outcome"]["ranked_organic"] is True


class TestReporting:
    def test_horizon_buckets(self):
        assert horizon_bucket(3.0) == 3
        assert horizon_bucket(6.5) == 6
        assert horizon_bucket(1.0) is None     # too early to speak to any horizon
        assert horizon_bucket(14.0) == 12

    def test_months_elapsed(self):
        start = datetime(2026, 1, 12, tzinfo=timezone.utc)
        assert months_elapsed(start, NOW) == 5.9  # 181 days / 30.44

    def test_summarize_coverage_and_small_n_honesty(self):
        p = _prediction()
        checks = {"p1": [{
            "checked_at": "2026-07-12T00:00:00+00:00", "months_elapsed": 6.0,
            "outcome": {"bar_cleared": True, "ranked_maps": False},
            "errors": {"bar_drift": 8, "rankab_residual": -0.45},
            "coverage": {"exp_leads": "no lead feed"},
        }]}
        report = summarize([p], checks)
        assert report["predictions"] == 1
        assert report["coverage"] == {"rev_win": 1, "rankab": 1, "leads": 0}
        # N=1 → stats withheld rather than misleading
        assert report["bar_drift_stats"] is None
        eng = report["engagements"][0]
        assert eng["market"] == "Locksmith @ Vancouver, WA"
        assert eng["checks"] == 1

    def test_summarize_counts_manual_leads(self):
        p = _prediction()
        checks = {"p1": [
            {"checked_at": "2026-07-01T00:00:00+00:00", "months_elapsed": 5.6,
             "outcome": {"note": "manual lead entry"}, "errors": {"leads_error": -3.0},
             "coverage": {}, "actual_leads_mo": 18, "leads_source": "manual"},
        ]}
        assert summarize([p], checks)["coverage"]["leads"] == 1
