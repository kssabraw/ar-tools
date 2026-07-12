"""Unit tests for the app-side BPS prospect-pipeline logic (pure only —
no network/DB). Fixture mimics the real BPS annual place-file shape: TWO
header rows combined, imputed-estimate Units columns plus a forbidden
'reported only' section the parser must skip."""
import pytest

from services.leadoff_permits import (
    _build_url,
    _looks_like_bps,
    assign_flags,
    combine_headers,
    compute_metrics,
    find_col,
    norm_place,
    parse_bps,
    permit_relevance,
)

BPS_FIXTURE = "\n".join([
    # header row 1 (units section, then reported-only section)
    "Survey,State,6-Digit,Place,1-unit,2-units,3-4 units,5+ units,"
    "1-unit rep,5+ units rep",
    # header row 2
    "Date,Code,ID,Name,Units,Units,Units,Units,Units,Units",
    # data rows
    "202599,48,999990,McKinney city,4000,60,40,900,3900,880",
    "202599,39,999991,Cleveland city,300,20,10,150,290,140",
    "202599,48,999992,McKinney city,3500,0,0,0,3400,0",  # dup: keep max
    "202599,06,999993,La Jolla CDP,50,0,0,0,50,0",
])


class TestParser:
    def test_headers_combine(self):
        cols = combine_headers("A,B", "x,y")
        assert cols == ["A x", "B y"]

    def test_find_col_forbid(self):
        cols = ["1-unit Units", "1-unit rep Units"]
        assert find_col(cols, "1-unit", "units", forbid=("rep",)) == 0
        with pytest.raises(ValueError, match="bps_layout_drift"):
            find_col(cols, "9-unit")

    def test_parse_shape_and_dup_max(self):
        out = parse_bps(BPS_FIXTURE)
        mck = out["48|mckinney"]
        assert mck["units_total"] == 4000 + 60 + 40 + 900  # imputed cols only
        assert mck["u1"] == 4000                            # max dup kept
        assert "39|cleveland" in out
        assert "06|la jolla" in out                         # CDP suffix stripped

    def test_place_suffix_stripping(self):
        assert norm_place("McKinney city") == "mckinney"
        assert norm_place("Winston-Salem town") == "winston salem"
        assert norm_place("La Jolla CDP") == "la jolla"


class TestMetrics:
    def test_boomtown_vs_rustbelt_shape(self):
        # the validation contract: per-capita separates the two worlds
        mck = compute_metrics(220_000, 5000, 4000, [4000, 3800, 3600])
        cle = compute_metrics(370_000, 480, 300, [500, 520, 510])
        assert mck["permits_pc"] > 5 * cle["permits_pc"]
        assert mck["permit_trend"] > 1.2          # accelerating
        assert cle["permit_trend"] < 1.0          # flat/declining
        assert mck["permit_sf_share"] == 0.8

    def test_null_honesty(self):
        m = compute_metrics(None, 100, 50, [])
        assert m["permits_pc"] is None and m["permit_trend"] is None
        assert m["permit_units_1yr"] == 100

    def test_zero_units(self):
        m = compute_metrics(50_000, 0, 0, [10, 10, 10])
        assert m["permit_sf_share"] is None and m["permit_trend"] == 0.0


class TestFlags:
    def _rows(self, n=20):
        rows = [{"permits_pc": float(i), "permit_trend": 1.0} for i in range(1, n + 1)]
        return rows

    def test_hot_needs_both_bars(self):
        rows = self._rows()
        rows[-1]["permit_trend"] = 1.5   # top pc + hot trend
        rows[-2]["permit_trend"] = 1.0   # top pc, flat trend → no flag
        assign_flags(rows)
        assert rows[-1]["permit_flag"] == "HOT-pipeline"
        assert rows[-2]["permit_flag"] == "-"

    def test_cold_flag(self):
        rows = self._rows()
        rows[0]["permit_trend"] = 0.5
        assign_flags(rows)
        assert rows[0]["permit_flag"] == "COLD-pipeline"

    def test_small_n_skips_flags(self):
        rows = self._rows(5)
        rows[-1]["permit_trend"] = 2.0
        assign_flags(rows)
        assert all(r["permit_flag"] == "-" for r in rows)

    def test_null_pc_never_flagged(self):
        rows = self._rows() + [{"permits_pc": None, "permit_trend": 9.9}]
        assign_flags(rows)
        assert rows[-1]["permit_flag"] == "-"


class TestUrlDiscovery:
    def test_build_url_covers_the_known_shapes(self):
        # the three subdir patterns × two year formats the worker probes
        assert _build_url(0, 0, "we", 2024) == \
            "https://www2.census.gov/econ/bps/Place/West%20Region/we2024a.txt"
        assert _build_url(1, 0, "we", 2024) == \
            "https://www2.census.gov/econ/bps/Place/West/we2024a.txt"
        assert _build_url(2, 0, "so", 2024) == \
            "https://www2.census.gov/econ/bps/Place/so2024a.txt"
        assert _build_url(0, 1, "mw", 2024) == \
            "https://www2.census.gov/econ/bps/Place/Midwest%20Region/mw24a.txt"

    def test_looks_like_bps_accepts_real_header(self):
        assert _looks_like_bps(BPS_FIXTURE) is True

    def test_looks_like_bps_rejects_404_page(self):
        assert _looks_like_bps("<html><body>404 Not Found</body></html>") is False


class TestRelevance:
    def test_construction_adjacent(self):
        for cat in ("Roofing contractor", "HVAC contractor", "Plumber",
                    "Landscaper", "Electrician", "Fence contractor",
                    "Concrete contractor", "Swimming pool contractor"):
            assert permit_relevance(cat) == "high"

    def test_not_adjacent(self):
        for cat in ("Locksmith", "Appliance repair service", "Moving company"):
            assert permit_relevance(cat) == "low"
