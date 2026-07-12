"""Unit tests for the LeadOff proximity pure core (no network/DB)."""
from services.leadoff_proximity import (
    bearing_deg,
    build_octant_coverage,
    build_proximity,
    haversine_miles,
    octant_of,
    placement_pins,
    proximity_opportunity,
    underserved_octants,
)

KC = (39.0997, -94.5786)  # Kansas City, MO centre


def pin(lat, lng, reviews=10, name="biz"):
    return {"lat": lat, "lng": lng, "review_count": reviews, "business_name": name}


class TestGeometry:
    def test_bearing_cardinals(self):
        lat, lng = KC
        assert round(bearing_deg(lat, lng, lat + 0.1, lng)) == 0        # north
        assert round(bearing_deg(lat, lng, lat, lng + 0.1)) in (90, 89)  # east
        assert round(bearing_deg(lat, lng, lat - 0.1, lng)) == 180      # south

    def test_octant_boundaries(self):
        assert octant_of(0) == "N"
        assert octant_of(22.4) == "N"
        assert octant_of(22.6) == "NE"
        assert octant_of(337.6) == "N"
        assert octant_of(180) == "S"
        assert octant_of(359.9) == "N"

    def test_haversine_sanity(self):
        # ~0.1° lat ≈ 6.9 miles
        d = haversine_miles(KC[0], KC[1], KC[0] + 0.1, KC[1])
        assert 6.5 < d < 7.5


class TestCoverage:
    def test_defense_is_review_weighted_and_distance_decayed(self):
        lat, lng = KC
        # one pin due north at ~6.9mi with 100 reviews:
        cov = build_octant_coverage(lat, lng, [pin(lat + 0.1, lng, 100)], 10)
        north = next(c for c in cov["octants"] if c["octant"] == "N")
        # 100 × 1/(1 + 6.9/2) ≈ 22.5
        assert 21 < north["defense"] < 24
        assert north["count"] == 1
        assert cov["used"] == 1

    def test_zero_review_pin_still_counts_minimally(self):
        lat, lng = KC
        cov = build_octant_coverage(lat, lng, [pin(lat + 0.05, lng, 0)], 10)
        north = next(c for c in cov["octants"] if c["octant"] == "N")
        assert north["defense"] > 0

    def test_out_of_radius_pins_skipped(self):
        lat, lng = KC
        cov = build_octant_coverage(lat, lng, [pin(lat + 1.0, lng)], 10)  # ~69mi
        assert cov["used"] == 0 and cov["skipped"] == 1

    def test_anchors_kept_strongest_first_max3(self):
        lat, lng = KC
        pins = [pin(lat + 0.05, lng, r, f"b{r}") for r in (5, 500, 50, 1)]
        cov = build_octant_coverage(lat, lng, pins, 10)
        north = next(c for c in cov["octants"] if c["octant"] == "N")
        assert [a["reviews"] for a in north["anchors"]] == [500, 50, 5]


class TestUnderservedAndOpportunity:
    def _octs(self, scores):
        from services.maps_octants import OCTANTS
        return [{"octant": o, "defense": s} for o, s in zip(OCTANTS, scores)]

    def test_weak_octants_below_frac_of_median(self):
        # defended median of [40,38,27,20,14,10] = 23.5; cut 0.25×23.5 ≈ 5.9
        # → only the two zero octants (10 clears the bar)
        octs = self._octs([40, 38, 27, 20, 14, 10, 0, 0])
        assert set(underserved_octants(octs, 0.25)) == {"W", "NW"}

    def test_concentrated_field_still_reads(self):
        # field in 3 of 8 octants — a raw all-8 median would be 0 and go blind
        octs = self._octs([90, 70, 40, 0, 0, 0, 0, 0])
        weak = underserved_octants(octs, 0.25)
        assert len(weak) == 5 and "N" not in weak

    def test_all_zero_market_returns_nothing(self):
        assert underserved_octants(self._octs([0] * 8), 0.25) == []

    def test_opportunity_zero_when_uniform_and_high_when_concentrated(self):
        assert proximity_opportunity(self._octs([10] * 8)) == 0.0
        concentrated = proximity_opportunity(self._octs([100, 0, 0, 0, 0, 0, 0, 0]))
        assert concentrated > 0.8
        assert proximity_opportunity(self._octs([0] * 8)) == 0.0


class TestPlacementAndPayload:
    def test_placement_pins_along_weak_bearings(self):
        lat, lng = KC
        pins_out = placement_pins(lat, lng, ["E", "SW", "N"], 9.0)
        assert len(pins_out) == 2  # capped at the two weakest
        east = pins_out[0]
        assert east["octant"] == "E"
        assert east["lng"] > lng  # east pin sits east of centre
        assert "google.com/maps?q=" in east["maps_url"]

    def test_thin_data_floor(self):
        lat, lng = KC
        result = build_proximity(lat, lng, [pin(lat + 0.05, lng)],
                                 radius_miles=10, min_pins=5, weak_frac=0.25)
        assert result["available"] is True
        assert result["thin_data"] is True
        assert result["underserved"] == [] and result["opportunity"] == 0.0

    def test_full_payload_shape(self):
        lat, lng = KC
        # a field anchored north+east, nothing south/west
        pins = ([pin(lat + 0.05, lng, 100)] * 3
                + [pin(lat, lng + 0.06, 80)] * 3
                + [pin(lat + 0.04, lng + 0.04, 60)] * 2)
        result = build_proximity(lat, lng, pins,
                                 radius_miles=10, min_pins=5, weak_frac=0.5)
        assert result["available"] and not result["thin_data"]
        assert result["pins_used"] == 8
        assert len(result["octants"]) == 8
        bars = {c["octant"]: c["bar_pct"] for c in result["octants"]}
        assert bars["N"] == 100  # strongest octant normalizes to 100
        assert bars["S"] == 0 and bars["W"] == 0
        # south/west side should surface as underserved
        assert {"S", "SW", "W"} & set(result["underserved"])
        assert result["placement"] and result["opportunity"] > 0.3
        assert "never a grade input" in result["note"]
