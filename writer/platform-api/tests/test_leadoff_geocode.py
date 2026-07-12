"""Unit tests for the LeadOff proximity geocode pure helpers (no network/DB)."""
from services.leadoff_geocode import (
    build_census_payload,
    chunked,
    coverage_summary,
    one_line_address,
    parse_census_response,
)


class TestOneLineAddress:
    def test_reconstructs_full_address(self):
        assert one_line_address("177 Broadway", "New York", "NY") == \
            "177 Broadway, New York, NY"

    def test_blank_address_is_none(self):
        # service-area business — no street address to geocode
        assert one_line_address("", "Kansas City", "MO") is None
        assert one_line_address(None, "KC", "MO") is None
        assert one_line_address("   ", "KC", "MO") is None

    def test_missing_city_state_still_returns_street(self):
        assert one_line_address("177 Broadway", None, None) == "177 Broadway"


class TestCensusParsing:
    def test_parses_match_rows_lon_lat_to_lat_lng(self):
        # Census returns coordinate as "lon,lat" (X,Y)
        resp = (
            '"1","177 Broadway, New York, NY","Match","Exact",'
            '"177 BROADWAY, NEW YORK, NY, 10007","-74.0106,40.7128","123","L"\n'
            '"2","nowhere","No_Match"\n'
        )
        out = parse_census_response(resp)
        assert out["1"] == (40.7128, -74.0106)   # (lat, lng)
        assert "2" not in out

    def test_empty_and_malformed_rows_skipped(self):
        assert parse_census_response("") == {}
        assert parse_census_response('"9","x","Match","Exact","addr","bad"\n') == {}

    def test_payload_is_multipart_with_benchmark(self):
        body, boundary = build_census_payload([("1", "177 Broadway, NY, NY")])
        text = body.decode()
        assert "Public_AR_Current" in text
        assert "177 Broadway" in text
        assert boundary in text


class TestChunking:
    def test_chunks(self):
        assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
        assert chunked([], 10) == []


class TestCoverage:
    def test_coverage_counts_sources_and_sab_gap(self):
        rows = [
            {"address": "177 Broadway", "lat": 40.7, "geo_source": "census"},
            {"address": "5 Grand St", "lat": 40.8, "geo_source": "census"},
            {"address": "", "lat": 39.1, "geo_source": "outscraper"},   # SAB filled
            {"address": "", "lat": None, "geo_source": None},           # SAB unfilled
            {"address": "9 Elm St", "lat": None, "geo_source": None},   # no census match
        ]
        s = coverage_summary(rows)
        assert s["competitors"] == 5
        assert s["addressed"] == 3
        assert s["geocoded"] == 3
        assert s["service_area_no_address"] == 2
        assert s["by_source"] == {"census": 2, "outscraper": 1}
        assert s["geocoded_pct"] == 0.6
