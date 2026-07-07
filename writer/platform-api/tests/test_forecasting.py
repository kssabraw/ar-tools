"""Unit tests for services.forecasting — the pure model."""

from __future__ import annotations

from datetime import date

from services import forecasting as fc


# ---------------------------------------------------------------------------
# CTR curve
# ---------------------------------------------------------------------------
def test_ctr_curve_shape():
    assert fc.ctr_for_position(1) == 0.28
    assert fc.ctr_for_position(10) == 0.024
    # interpolation between integer positions
    assert fc.ctr_for_position(1.5) == round((0.28 + 0.155) / 2, 4)
    # the tail decays and never goes to zero
    assert fc.ctr_for_position(15) == fc._CTR_11_20
    assert fc.ctr_for_position(25) == fc._CTR_21_30
    assert fc.ctr_for_position(80) == fc._CTR_BEYOND
    assert fc.ctr_for_position(None) == 0.28  # defensive: treated as pos 1


def test_ctr_monotonic_decreasing():
    vals = [fc.ctr_for_position(p) for p in range(1, 40)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))


# ---------------------------------------------------------------------------
# trend fitting + projection
# ---------------------------------------------------------------------------
def _series(start_day: int, positions: list[float], step: int = 3) -> list[tuple[int, float]]:
    return [(start_day + i * step, p) for i, p in enumerate(positions)]


def test_fit_trend_improving_is_negative():
    pts = _series(1000, [12, 11, 10.5, 10, 9, 8.5, 8, 7.5])  # 21-day span
    slope = fc.fit_trend(pts)
    assert slope is not None and slope < 0


def test_fit_trend_refuses_thin_data():
    assert fc.fit_trend(_series(1000, [10, 9, 8])) is None          # <4 points
    assert fc.fit_trend([(1000, 10), (1002, 9), (1004, 8), (1006, 7)]) is None  # <14-day span
    assert fc.fit_trend([]) is None


def test_project_position_clamps():
    assert fc.project_position(5.0, -0.1, 30) == 2.0
    assert fc.project_position(2.0, -0.1, 90) == 1.0     # clamps at 1
    assert fc.project_position(95.0, 0.5, 30) == 100.0   # clamps at 100
    assert fc.project_position(8.0, None, 30) == 8.0     # no trend → flat
    assert fc.project_position(None, -0.1, 30) is None


# ---------------------------------------------------------------------------
# keyword forecast
# ---------------------------------------------------------------------------
def test_forecast_keyword_gsc_anchors_on_actual_clicks():
    pts = _series(1000, [12, 11, 10, 9, 8, 7, 6, 5])
    f = fc.forecast_keyword("roof repair", pts, 5.0, actual_clicks_30d=40,
                            volume=1000, cpc=12.0, clicks_source="gsc")
    assert f["clicks_per_month_now"] == 40.0            # the GSC actual, not volume×ctr
    assert f["clicks_source"] == "gsc"
    assert f["trend_per_week"] < 0                      # improving
    assert f["projected_position_90d"] <= f["current_position"]
    # projections scale the actual by the CTR ratio → improving rank ⇒ more clicks
    assert f["clicks_per_month_90d"] > f["clicks_per_month_now"]
    assert f["value_per_month_now"] == 480              # 40 × $12


def test_forecast_keyword_ctr_model_and_missing_market():
    f = fc.forecast_keyword("kw", [], 8.0, None, volume=500, cpc=None, clicks_source="ctr_model")
    assert f["clicks_per_month_now"] == round(500 * fc.ctr_for_position(8.0), 1)
    assert f["value_per_month_now"] is None             # no CPC → no dollars
    assert f["confidence"] == "low"
    bare = fc.forecast_keyword("kw", [], 8.0, None, volume=None, cpc=None, clicks_source="ctr_model")
    assert bare["clicks_per_month_now"] is None and bare["clicks_source"] == "none"


# ---------------------------------------------------------------------------
# quick-win scenario
# ---------------------------------------------------------------------------
def test_quick_win_scenario_band_and_math():
    forecasts = [
        fc.forecast_keyword("in-band", [], 8.0, None, 1000, 5.0, "ctr_model"),
        fc.forecast_keyword("page-two", [], 15.0, None, 400, 10.0, "ctr_model"),
        fc.forecast_keyword("already-top", [], 2.0, None, 5000, 5.0, "ctr_model"),  # < band
        fc.forecast_keyword("too-deep", [], 40.0, None, 900, 5.0, "ctr_model"),     # > band
        fc.forecast_keyword("no-volume", [], 9.0, None, None, None, "ctr_model"),   # skipped
    ]
    s = fc.quick_win_scenario(forecasts)
    names = [i["keyword"] for i in s["keywords"]]
    assert set(names) == {"in-band", "page-two"}
    assert s["skipped_no_volume"] == 1
    expected_in_band = round(1000 * (fc.ctr_for_position(3) - fc.ctr_for_position(8.0)), 1)
    row = next(i for i in s["keywords"] if i["keyword"] == "in-band")
    assert row["extra_clicks_per_month"] == expected_in_band
    assert s["total_extra_clicks_per_month"] > 0
    assert s["total_extra_value_per_month"] > 0


# ---------------------------------------------------------------------------
# metric projection + goal trajectory
# ---------------------------------------------------------------------------
def test_project_metric_linear():
    assert fc.project_metric_linear(120, 100, 1) == 140    # +20/window
    assert fc.project_metric_linear(120, 100, 3) == 180
    assert fc.project_metric_linear(50, 100, 2) == 0       # declines floor at 0


def test_goal_projection_keyword_position():
    today = date(2026, 7, 7)
    kw_f = {
        "roof repair": {
            "keyword": "roof repair", "current_position": 8.0,
            "trend_per_week": -0.7, "confidence": "medium",
        }
    }
    goal = {"goal_type": "keyword_position", "label": "roof repair to top 3",
            "keyword": "Roof Repair", "target_value": 3.0, "due_date": "2026-09-05"}
    p = fc.goal_projection(goal, kw_f, today)
    assert p is not None and p["on_trajectory"] is True   # 60 days × -0.1/day → ~2
    # a flat keyword misses the target
    kw_f["roof repair"]["trend_per_week"] = 0.0
    p = fc.goal_projection(goal, kw_f, today)
    assert p["on_trajectory"] is False
    # overdue goal → no projection
    assert fc.goal_projection({**goal, "due_date": "2026-01-01"}, kw_f, today) is None
    # unknown keyword → None
    assert fc.goal_projection({**goal, "keyword": "zzz"}, kw_f, today) is None
