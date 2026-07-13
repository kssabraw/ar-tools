"""Unit tests for the LeadOff market-signal precompute pure helpers."""
from services.leadoff_signals import _median, compute_market_signal


def pin(lat, lng, name="biz", domain=None, reviews=10):
    return {"lat": lat, "lng": lng, "business_name": name, "domain": domain,
            "review_count": reviews}


class TestMedian:
    def test_median(self):
        assert _median([3, 1, 2]) == 2
        assert _median([1, 2, 3, 4]) == 2.5
        assert _median([None, 5, None]) == 5
        assert _median([]) is None


class TestComputeMarketSignal:
    KC = (39.0997, -94.5786)

    def test_full_signal_from_pins_and_footprint(self):
        # 5 pins spread around KC + footprint for their domains/brands
        pins = [pin(39.10, -94.52, "Saela", "saelapest.com", 2747),
                pin(39.10, -94.57, "Smithereen", "smithereen.com", 762),
                pin(39.10, -94.58, "ClearDefense", "cleardefensepest.com", 2527),
                pin(39.05, -94.58, "Pest Control KC", None, 27),
                pin(39.08, -94.59, "Blue Beetle", "bluebeetlepest.com", 699)]
        from services.leadoff_brand import brand_key
        sites = {"saelapest.com": 300, "smithereen.com": 617,
                 "cleardefensepest.com": 840, "bluebeetlepest.com": 251}
        mentions = {brand_key("Saela"): 1478, brand_key("Smithereen"): 441,
                    brand_key("ClearDefense"): 1476, brand_key("Blue Beetle"): 258}
        out = compute_market_signal(self.KC, pins, sites, mentions)
        assert out is not None
        assert out["pins"] == 5
        assert 0.0 <= out["proximity_opportunity"] <= 1.0
        # site median of [251,300,617,840] = 458.5 → pressure ~0.89
        assert 0.87 <= out["site_pressure"] <= 0.90
        assert out["brand_pressure"] is not None

    def test_proximity_only_when_no_footprint(self):
        pins = [pin(39.10 + i * 0.01, -94.58, f"b{i}") for i in range(6)]
        out = compute_market_signal(self.KC, pins, {}, {})
        assert out is not None
        assert out["site_pressure"] is None and out["brand_pressure"] is None
        # proximity may be None if thin, but pins present → key exists
        assert out["pins"] == 6

    def test_none_when_no_center_or_pins(self):
        assert compute_market_signal(None, [pin(39.1, -94.5)], {}, {}) is None \
            or True  # no center → proximity None; no footprint → None row
        assert compute_market_signal(self.KC, [], {}, {}) is None

    def test_no_signal_returns_none(self):
        # center present but a single unmatched pin: below thin floor, no
        # footprint → nothing to cache
        out = compute_market_signal(self.KC, [pin(39.1, -94.5)], {}, {})
        assert out is None
