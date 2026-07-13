"""Unit tests for the LeadOff Beatability reading score (pure)."""
from services.leadoff_beatability import (
    attach_beatability,
    beatability,
    beatability_band,
    with_beatability,
)


class TestBeatability:
    def test_soft_field_scores_high(self):
        # Jersey City tree service: beat #3 with 6 reviews, few holders, avg ★.
        s = beatability(rev_win=6, exact_open=3, rating=4.72)
        assert s >= 66 and beatability_band(s) == "soft"

    def test_tough_field_scores_low(self):
        # a brutal field: p90+ review bar, saturated category, top-rated field
        s = beatability(rev_win=172, exact_open=29, rating=5.0)
        assert s < 34 and beatability_band(s) == "tough"

    def test_median_field_is_moderate(self):
        # sit every signal at its board median → mid of the scale
        s = beatability(rev_win=30, exact_open=7, rating=4.8)
        assert 34 <= s < 66 and beatability_band(s) == "moderate"

    def test_rev_win_dominates(self):
        # same holders/rating, only the review bar differs → soft beats tough
        soft = beatability(rev_win=4, exact_open=10, rating=4.8)
        tough = beatability(rev_win=150, exact_open=10, rating=4.8)
        assert soft > tough

    def test_monotonic_in_each_signal(self):
        base = beatability(rev_win=30, exact_open=7, rating=4.8)
        assert beatability(rev_win=10, exact_open=7, rating=4.8) > base   # fewer reviews
        assert beatability(rev_win=30, exact_open=2, rating=4.8) > base   # fewer holders
        assert beatability(rev_win=30, exact_open=7, rating=4.4) > base   # weaker incumbents

    def test_missing_signals_renormalize(self):
        # only rev_win present → scored off it alone, not dragged to 0
        only_rev = beatability(rev_win=6, exact_open=None, rating=None)
        assert only_rev is not None and only_rev >= 66
        # rating absent (the common case) still scores off rev+holders
        no_rating = beatability(rev_win=6, exact_open=3, rating=None)
        assert no_rating is not None and no_rating >= 66

    def test_no_signal_is_none(self):
        assert beatability(None, None, None) is None
        assert beatability(rev_win=None, exact_open=None, rating=0) is None
        assert beatability_band(None) is None

    def test_bad_types_are_ignored(self):
        assert beatability(rev_win="x", exact_open=None, rating=None) is None
        assert beatability(rev_win=6, exact_open="", rating=None) is not None


class TestAttach:
    def test_with_beatability_adds_fields(self):
        row = {"city_name": "Jersey City", "rev_win": 6, "exact_open": 3,
               "rating": 4.72}
        out = with_beatability(row)
        assert out["city_name"] == "Jersey City"          # row preserved
        assert out["beatability"] >= 66
        assert out["beatability_band"] == "soft"

    def test_attach_maps_over_list(self):
        rows = [{"rev_win": 6, "exact_open": 3, "rating": 4.7},
                {"rev_win": 172, "exact_open": 29, "rating": 5.0}]
        out = attach_beatability(rows)
        assert out[0]["beatability_band"] == "soft"
        assert out[1]["beatability_band"] == "tough"
