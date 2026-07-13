"""Unit tests for the LeadOff Census-ACS income backfill (pure helpers)."""
from services.leadoff_income import (
    best_by_norm,
    coerce_income,
    coerce_pop,
    match_places,
    normalize_place_name,
    parse_acs_rows,
)


class TestNormalize:
    def test_strips_government_type_suffix(self):
        assert normalize_place_name("Cheyenne city, Wyoming") == "cheyenne"
        assert normalize_place_name("Springfield town, Vermont") == "springfield"
        assert normalize_place_name("Some Place CDP, Texas") == "some place"

    def test_keeps_real_city_in_name(self):
        # only the trailing gov-type token is stripped, not a real "City"
        assert normalize_place_name("Lake Havasu City city, Arizona") \
            == "lake havasu city"

    def test_drops_balance_marker(self):
        assert normalize_place_name("Athens-Clarke County (balance), Georgia") \
            == "athens-clarke county"

    def test_handles_periods(self):
        assert normalize_place_name("St. Louis city, Missouri") == "st. louis"


class TestCoerce:
    def test_income_sentinels_are_none(self):
        assert coerce_income("-666666666") is None
        assert coerce_income("") is None
        assert coerce_income(None) is None
        assert coerce_income("72479") == 72479

    def test_pop_floors_at_zero(self):
        assert coerce_pop("-5") == 0
        assert coerce_pop("bad") == 0
        assert coerce_pop("65132") == 65132


class TestParseAndMatch:
    HEADER = ["NAME", "B19013_001E", "B01003_001E", "state", "place"]

    def test_parse_skips_header_and_no_income(self):
        data = [self.HEADER,
                ["Cheyenne city, Wyoming", "72479", "65132", "56", "13900"],
                ["Ghost town, Wyoming", "-666666666", "0", "56", "99999"]]
        rows = parse_acs_rows(data)
        assert len(rows) == 1
        assert rows[0]["norm"] == "cheyenne" and rows[0]["income"] == 72479

    def test_best_by_norm_prefers_most_populous(self):
        places = [{"norm": "springfield", "income": 40_000, "population": 5_000,
                   "name": "Springfield CDP, X"},
                  {"norm": "springfield", "income": 55_000, "population": 90_000,
                   "name": "Springfield city, X"}]
        best = best_by_norm(places)
        assert best["springfield"]["income"] == 55_000

    def test_match_places_to_city_index(self):
        places = [{"norm": "cheyenne", "income": 72479, "population": 65132,
                   "name": "Cheyenne city, Wyoming"},
                  {"norm": "nowhere", "income": 50_000, "population": 1_000,
                   "name": "Nowhere city, Wyoming"}]
        matched = match_places(places, {"cheyenne": 42})
        assert matched == {42: {"income": 72479,
                                "matched_name": "Cheyenne city, Wyoming"}}
