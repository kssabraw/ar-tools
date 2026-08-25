"""Unit tests for the LeadOff GBP Placement Advisor pure core (no network/DB).

Covers the plan §3 math: demand/pressure gravity sums, market-relative min-max
scoring, weight-0 households-only parity, zone spacing, arbitrary-point scoring
+ percentile, and the honesty-relevant edge cases (empty field, flat surface).
"""
from services.leadoff_placement import (
    build_demand_surface,
    build_zones,
    demand_access,
    households_within,
    nearest_competitor_miles,
    pressure,
    score_grid,
    score_point,
    select_zones,
    zone_narrative,
)

# Little Rock, AR centre (the Phase-0 test market).
LR = (34.7465, -92.2896)


def bg(lat, lng, households=1000, income=None, geoid="x", housing_age=None):
    return {"geoid": geoid, "lat": lat, "lng": lng, "households": households,
            "median_income": income, "housing_age": housing_age}


def pin(lat, lng, reviews=10):
    return {"lat": lat, "lng": lng, "review_count": reviews}


class TestDemandSurface:
    def test_weight_zero_is_households_only(self):
        """The v1 default (both weights 0) → multiplier EXACTLY 1.0, so the
        weighted household count equals the raw count (the parity the plan pins)."""
        rows = [bg(LR[0], LR[1], 1500, income=90000),
                bg(LR[0] + 0.05, LR[1], 500, income=20000)]
        surface = build_demand_surface(rows, income_weight=0.0,
                                       housing_age_weight=0.0)
        assert [r["demand_multiplier"] for r in surface] == [1.0, 1.0]
        assert [r["weighted_households"] for r in surface] == [1500, 500]

    def test_income_weight_lifts_high_income_bg(self):
        rows = [bg(LR[0], LR[1], 1000, income=90000),
                bg(LR[0] + 0.05, LR[1], 1000, income=20000)]
        surface = build_demand_surface(rows, income_weight=0.5,
                                       housing_age_weight=0.0)
        hi, lo = surface[0], surface[1]
        assert hi["demand_multiplier"] == 1.5   # norm(top)=1 → 1 + 0.5*1
        assert lo["demand_multiplier"] == 1.0    # norm(bottom)=0 → 1 + 0.5*0
        assert hi["weighted_households"] > lo["weighted_households"]

    def test_drops_invalid_and_zero_household_rows(self):
        rows = [bg(None, LR[1], 1000), bg(LR[0], None, 1000),
                bg(LR[0], LR[1], 0), bg(LR[0], LR[1], 800)]
        surface = build_demand_surface(rows)
        assert len(surface) == 1
        assert surface[0]["households"] == 800

    def test_housing_age_old_share(self):
        # A block group all built pre-1980 vs all built post-2010.
        old = bg(LR[0], LR[1], 1000, housing_age={
            "B25034_001E": 100, "B25034_007E": 60, "B25034_011E": 40})
        new = bg(LR[0] + 0.05, LR[1], 1000, housing_age={
            "B25034_001E": 100, "B25034_002E": 100})
        surface = build_demand_surface([old, new], housing_age_weight=0.5)
        assert surface[0]["demand_multiplier"] > surface[1]["demand_multiplier"]


class TestGravitySums:
    def test_demand_access_decays_with_distance(self):
        surface = build_demand_surface([bg(LR[0], LR[1], 1000)])
        near = demand_access(LR[0], LR[1], surface, decay_miles=5.0)
        far = demand_access(LR[0] + 0.2, LR[1], surface, decay_miles=5.0)  # ~14mi
        assert near > far > 0

    def test_pressure_review_weighted(self):
        strong = [pin(LR[0], LR[1], reviews=200)]
        weak = [pin(LR[0], LR[1], reviews=1)]
        assert (pressure(LR[0] + 0.01, LR[1], strong, 2.0)
                > pressure(LR[0] + 0.01, LR[1], weak, 2.0))

    def test_pressure_min_reviews_floor(self):
        # A zero-review competitor still exerts pressure (max(reviews,1)).
        assert pressure(LR[0], LR[1], [pin(LR[0], LR[1], reviews=0)], 2.0) > 0

    def test_pressure_skips_coordless_pins(self):
        assert pressure(LR[0], LR[1], [{"review_count": 50}], 2.0) == 0.0

    def test_households_within_catchment(self):
        rows = [bg(LR[0], LR[1], 1000),
                bg(LR[0] + 0.3, LR[1], 500)]  # ~20 mi away
        surface = build_demand_surface(rows)
        assert households_within(LR[0], LR[1], surface, 5.0) == 1000

    def test_nearest_competitor(self):
        # Nearest is the +0.05° pin (~3.5 mi); the farther +0.2° pin is ignored.
        pins = [pin(LR[0] + 0.05, LR[1]), pin(LR[0] + 0.2, LR[1])]
        d = nearest_competitor_miles(LR[0], LR[1], pins)
        assert 3.0 < d < 4.0

    def test_nearest_competitor_empty(self):
        assert nearest_competitor_miles(LR[0], LR[1], []) is None


class TestScoreGrid:
    def test_score_range_and_norm_context(self):
        surface = build_demand_surface([bg(LR[0], LR[1], 5000)])
        pins = [pin(LR[0] + 0.03, LR[1], 100)]
        grid = score_grid(LR[0], LR[1], surface, pins, radius_miles=5)
        cells = grid["cells"]
        assert len(cells) == 11 * 11   # radius 5 @ 1mi → 11x11 lattice
        assert all(0 <= c["score"] <= 100 for c in cells)
        assert set(grid["norm"]) >= {"demand_lo", "demand_hi",
                                     "pressure_lo", "pressure_hi",
                                     "demand_decay_miles", "pressure_decay_miles"}

    def test_high_demand_low_pressure_wins(self):
        # Demand concentrated NE, a strong competitor sitting SW.
        surface = build_demand_surface([bg(LR[0] + 0.04, LR[1] + 0.04, 8000)])
        pins = [pin(LR[0] - 0.04, LR[1] - 0.04, 300)]
        grid = score_grid(LR[0], LR[1], surface, pins, radius_miles=5)
        best = max(grid["cells"], key=lambda c: c["score"])
        # Best cell leans toward the demand (north/east of centre), away from
        # the SW competitor.
        assert best["row"] >= 5 and best["col"] >= 5

    def test_empty_field_all_relief(self):
        """No competitors → pressure is flat 0 everywhere → the score reduces to
        the demand term (norm(demand) × 100). No crash on empty pins."""
        surface = build_demand_surface([bg(LR[0] + 0.03, LR[1], 4000)])
        grid = score_grid(LR[0], LR[1], surface, [], radius_miles=4)
        assert max(c["score"] for c in grid["cells"]) > 0


class TestScorePoint:
    def test_percentile_and_scale_consistency(self):
        surface = build_demand_surface([bg(LR[0] + 0.03, LR[1], 6000)])
        pins = [pin(LR[0] - 0.03, LR[1], 150)]
        grid = score_grid(LR[0], LR[1], surface, pins, radius_miles=5)
        best = max(grid["cells"], key=lambda c: c["score"])
        # Scoring the best cell's own coordinate reproduces ~its score and a
        # top percentile (uses the SAME norm context).
        sp = score_point(best["lat"], best["lng"], surface, pins, grid)
        assert abs(sp["score"] - best["score"]) < 0.5
        assert sp["percentile"] >= 95
        assert "households_reachable" in sp

    def test_point_outside_field(self):
        surface = build_demand_surface([bg(LR[0], LR[1], 3000)])
        grid = score_grid(LR[0], LR[1], surface, [], radius_miles=4)
        far = score_point(LR[0] + 1.0, LR[1], surface, [], grid)  # ~69 mi away
        assert far["score"] == 0.0
        assert far["nearest_competitor_miles"] is None


class TestZones:
    def test_min_separation_enforced(self):
        # Two demand blobs ~4 mi apart; zones must respect a 2-mi spacing and
        # not clump on the single hottest ridge.
        surface = build_demand_surface([
            bg(LR[0] + 0.04, LR[1], 5000),
            bg(LR[0] - 0.04, LR[1], 5000)])
        grid = score_grid(LR[0], LR[1], surface, [], radius_miles=6)
        zones = select_zones(grid["cells"], zone_count=4,
                             min_separation_miles=2.0)
        from services.leadoff_placement import haversine_miles
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                d = haversine_miles(zones[i]["lat"], zones[i]["lng"],
                                    zones[j]["lat"], zones[j]["lng"])
                assert d >= 2.0

    def test_zone_count_cap(self):
        surface = build_demand_surface([bg(LR[0], LR[1], 5000)])
        grid = score_grid(LR[0], LR[1], surface, [], radius_miles=8)
        zones = select_zones(grid["cells"], zone_count=3,
                             min_separation_miles=2.0)
        assert len(zones) <= 3

    def test_build_zones_enriches_and_ranks(self):
        surface = build_demand_surface([bg(LR[0] + 0.03, LR[1], 7000)])
        pins = [pin(LR[0] - 0.05, LR[1], 80)]
        out = build_zones(LR[0], LR[1], surface, pins, radius_miles=5,
                          zone_count=4, min_separation_miles=2.0)
        assert out["zones"]
        top = out["zones"][0]
        assert top["rank"] == 1 and top["is_top"] is True
        assert "narrative" in top and top["narrative"]
        assert "market only" in out["note"]

    def test_zero_score_cells_not_selected(self):
        # A market with no demand surface → every cell scores 0 → no zones.
        grid = score_grid(LR[0], LR[1], [], [], radius_miles=4)
        assert select_zones(grid["cells"], zone_count=4,
                            min_separation_miles=2.0) == []


class TestNarrative:
    def test_pressure_bands(self):
        light = zone_narrative({"score": 80, "households_reachable": 12000,
                                "pressure_norm": 0.1,
                                "nearest_competitor_miles": 4.0})
        heavy = zone_narrative({"score": 40, "households_reachable": 12000,
                                "pressure_norm": 0.9,
                                "nearest_competitor_miles": 0.5})
        assert "light" in light and "heavy" in heavy
        assert "12,000 households" in light
