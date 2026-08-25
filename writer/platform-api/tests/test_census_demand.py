"""Unit tests for the LeadOff Census demand pure helpers (no network/DB)."""
from services.census_demand import (
    bbox_for,
    coerce_int,
    is_stale,
    merge_demand_rows,
    parse_acs_blockgroups,
    parse_tigerweb_centroids,
)


class TestCoerce:
    def test_valid_and_sentinels(self):
        assert coerce_int("1200") == 1200
        assert coerce_int(1200.0) == 1200
        assert coerce_int("-666666666") is None   # ACS jam value
        assert coerce_int(None) is None
        assert coerce_int("") is None
        assert coerce_int("abc") is None


class TestParseAcs:
    HEADER = ["NAME", "B25001_001E", "B01003_001E", "B19013_001E",
              "B25034_001E", "B25034_007E", "B25034_011E",
              "state", "county", "tract", "block group"]

    def _row(self, hh, pop, inc, total=100, b7=30, b11=20,
             state="05", county="119", tract="004500", bg="1"):
        return ["BG", str(hh), str(pop), str(inc),
                str(total), str(b7), str(b11), state, county, tract, bg]

    def test_geoid_assembled_and_fields(self):
        out = parse_acs_blockgroups([self.HEADER,
                                     self._row(1000, 2500, 65000)])
        assert len(out) == 1
        bg = out[0]
        assert bg["geoid"] == "051190045001"
        assert bg["county_fips"] == "05119"
        assert bg["households"] == 1000
        assert bg["population"] == 2500
        assert bg["median_income"] == 65000
        assert bg["housing_age"]["B25034_007E"] == 30

    def test_drops_zero_household_rows(self):
        out = parse_acs_blockgroups([self.HEADER, self._row(0, 0, 40000)])
        assert out == []

    def test_income_sentinel_becomes_none(self):
        out = parse_acs_blockgroups([self.HEADER,
                                     self._row(800, 1900, -666666666)])
        assert out[0]["median_income"] is None

    def test_empty_and_headeronly(self):
        assert parse_acs_blockgroups([]) == []
        assert parse_acs_blockgroups([self.HEADER]) == []

    def test_missing_required_column(self):
        # No 'block group' geo column → can't build a GEOID → nothing parsed.
        bad = ["NAME", "B25001_001E", "state", "county", "tract"]
        assert parse_acs_blockgroups([bad, ["x", "10", "05", "119", "004500"]]) == []


class TestParseCentroids:
    def test_geoid_to_latlng(self):
        resp = {"features": [
            {"attributes": {"GEOID": "051190045001",
                            "CENTLAT": "+34.7465", "CENTLON": "-092.2896"}},
            {"attributes": {"GEOID": "051190045002",
                            "INTPTLAT": "+34.75", "INTPTLON": "-92.30"}},
            {"attributes": {"GEOID": "", "CENTLAT": "+1", "CENTLON": "+1"}},
        ]}
        out = parse_tigerweb_centroids(resp)
        assert out["051190045001"] == (34.7465, -92.2896)
        assert out["051190045002"] == (34.75, -92.30)
        assert "" not in out    # blank GEOID dropped

    def test_empty(self):
        assert parse_tigerweb_centroids({}) == {}
        assert parse_tigerweb_centroids({"features": []}) == {}


class TestBbox:
    def test_encloses_radius(self):
        lat, lng = 34.7465, -92.2896
        lat_min, lat_max, lng_min, lng_max = bbox_for(lat, lng, 10)
        # 10 mi ≈ 0.145° lat; longitude wider (cos(34.7)≈0.82)
        assert round(lat_max - lat, 3) == round(lat - lat_min, 3)
        assert (lat_max - lat) > 0.14 and (lat_max - lat) < 0.15
        assert (lng_max - lng) > (lat_max - lat)   # lng degrees wider at this lat


class TestMerge:
    def test_joins_and_drops_uncentroided(self):
        acs = [
            {"geoid": "A", "county_fips": "05119", "households": 900,
             "population": 2000, "median_income": 50000, "housing_age": {}},
            {"geoid": "B", "county_fips": "05119", "households": 700,
             "population": 1500, "median_income": None, "housing_age": {}},
        ]
        centroids = {"A": (34.7, -92.2)}   # B has no centroid
        rows = merge_demand_rows(acs, centroids, "2026-08-25T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["geoid"] == "A"
        assert rows[0]["lat"] == 34.7 and rows[0]["lng"] == -92.2
        assert rows[0]["pulled_at"] == "2026-08-25T00:00:00Z"


class TestStale:
    def test_fresh_vs_stale(self):
        assert is_stale("2000-01-01T00:00:00+00:00", 365) is True
        assert is_stale("2999-01-01T00:00:00+00:00", 365) is False
        assert is_stale(None, 365) is True
        assert is_stale("not-a-date", 365) is True
