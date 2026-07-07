"""Unit tests for the GBP performance-metrics pure helpers.

No network / no DB: normalize_location_id, parse_time_series, classify_access_error
(gbp_performance_service) + compute_window, parse_metric_rows, compute_metric_growth
(gbp_metrics_ingest). The live Google calls + DB upserts are integration-tested.
"""

from __future__ import annotations

from datetime import date

import pytest

from services import gbp_metrics_ingest as ingest
from services import gbp_performance_service as gbp


# ----------------------------------------------------------------------------
# normalize_location_id
# ----------------------------------------------------------------------------
def test_normalize_location_id_bare_id():
    assert gbp.normalize_location_id("1234567890") == "locations/1234567890"


def test_normalize_location_id_already_prefixed():
    assert gbp.normalize_location_id("locations/1234567890") == "locations/1234567890"


def test_normalize_location_id_from_full_resource_path():
    assert gbp.normalize_location_id("accounts/42/locations/99") == "locations/99"


def test_normalize_location_id_strips_whitespace():
    assert gbp.normalize_location_id("  locations/7 ") == "locations/7"


@pytest.mark.parametrize("bad", ["", "   ", "loc ations/1", "foo/bar"])
def test_normalize_location_id_rejects_bad(bad):
    with pytest.raises(ValueError):
        gbp.normalize_location_id(bad)


# ----------------------------------------------------------------------------
# parse_time_series
# ----------------------------------------------------------------------------
def _payload():
    return {
        "multiDailyMetricTimeSeries": [
            {
                "dailyMetricTimeSeries": [
                    {
                        "dailyMetric": "CALL_CLICKS",
                        "timeSeries": {
                            "datedValues": [
                                {"date": {"year": 2026, "month": 7, "day": 1}, "value": "12"},
                                # value omitted → 0
                                {"date": {"year": 2026, "month": 7, "day": 2}},
                            ]
                        },
                    },
                    {
                        "dailyMetric": "WEBSITE_CLICKS",
                        "timeSeries": {
                            "datedValues": [
                                {"date": {"year": 2026, "month": 7, "day": 1}, "value": "3"},
                            ]
                        },
                    },
                ]
            }
        ]
    }


def test_parse_time_series_flattens_and_zero_fills():
    out = gbp.parse_time_series(_payload())
    assert {"metric": "CALL_CLICKS", "date": "2026-07-01", "value": 12} in out
    assert {"metric": "CALL_CLICKS", "date": "2026-07-02", "value": 0} in out
    assert {"metric": "WEBSITE_CLICKS", "date": "2026-07-01", "value": 3} in out
    assert len(out) == 3


def test_parse_time_series_pads_date_components():
    payload = {
        "multiDailyMetricTimeSeries": [
            {"dailyMetricTimeSeries": [
                {"dailyMetric": "CALL_CLICKS",
                 "timeSeries": {"datedValues": [
                     {"date": {"year": 2026, "month": 1, "day": 5}, "value": "1"}]}}]}
        ]
    }
    assert gbp.parse_time_series(payload)[0]["date"] == "2026-01-05"


def test_parse_time_series_empty_and_missing_date():
    assert gbp.parse_time_series({}) == []
    # A dated value with an unresolvable date is skipped, not crashed on.
    payload = {
        "multiDailyMetricTimeSeries": [
            {"dailyMetricTimeSeries": [
                {"dailyMetric": "CALL_CLICKS",
                 "timeSeries": {"datedValues": [{"value": "9"}]}}]}
        ]
    }
    assert gbp.parse_time_series(payload) == []


# ----------------------------------------------------------------------------
# classify_access_error
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("code", [401, 403])
def test_classify_no_access(code):
    assert gbp.classify_access_error(code).status == "no_access"


def test_classify_quota_is_error():
    r = gbp.classify_access_error(429)
    assert r.status == "error" and "quota" in (r.detail or "")


def test_classify_unknown():
    assert gbp.classify_access_error(None).status == "error"


# ----------------------------------------------------------------------------
# compute_window
# ----------------------------------------------------------------------------
def test_compute_window_inclusive():
    start, end = ingest.compute_window(date(2026, 7, 7), 7)
    assert end == date(2026, 7, 7)
    assert start == date(2026, 7, 1)  # 7 days inclusive


def test_compute_window_floors_at_one():
    start, end = ingest.compute_window(date(2026, 7, 7), 0)
    assert start == end == date(2026, 7, 7)


# ----------------------------------------------------------------------------
# parse_metric_rows
# ----------------------------------------------------------------------------
def test_parse_metric_rows_shapes_upsert_records():
    rows = ingest.parse_metric_rows(
        "loc-1",
        [
            {"metric": "CALL_CLICKS", "date": "2026-07-01", "value": 5},
            {"metric": "", "date": "2026-07-01", "value": 9},   # dropped (no metric)
            {"metric": "WEBSITE_CLICKS", "date": None, "value": 1},  # dropped (no date)
        ],
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["location_row_id"] == "loc-1"
    assert r["metric"] == "CALL_CLICKS" and r["date"] == "2026-07-01" and r["value"] == 5


# ----------------------------------------------------------------------------
# compute_metric_growth
# ----------------------------------------------------------------------------
def test_compute_metric_growth_current_vs_prior():
    end = date(2026, 7, 10)
    rows = [
        # current window (2026-07-06..07-10, window=5)
        {"date": "2026-07-10", "metric": "CALL_CLICKS", "value": 4},
        {"date": "2026-07-06", "metric": "CALL_CLICKS", "value": 6},
        # prior window (2026-07-01..07-05)
        {"date": "2026-07-05", "metric": "CALL_CLICKS", "value": 5},
        # out of both windows entirely — ignored
        {"date": "2026-06-01", "metric": "CALL_CLICKS", "value": 99},
    ]
    growth = ingest.compute_metric_growth(rows, end, window_days=5)
    g = growth["CALL_CLICKS"]
    assert g["current"] == 10
    assert g["previous"] == 5
    assert g["delta"] == 5
    assert g["pct"] == 100.0


def test_compute_metric_growth_pct_none_when_prior_zero():
    end = date(2026, 7, 10)
    rows = [{"date": "2026-07-10", "metric": "WEBSITE_CLICKS", "value": 3}]
    growth = ingest.compute_metric_growth(rows, end, window_days=5)
    assert growth["WEBSITE_CLICKS"]["previous"] == 0
    assert growth["WEBSITE_CLICKS"]["pct"] is None


def test_compute_metric_growth_metric_filter():
    end = date(2026, 7, 10)
    rows = [
        {"date": "2026-07-10", "metric": "CALL_CLICKS", "value": 3},
        {"date": "2026-07-10", "metric": "WEBSITE_CLICKS", "value": 8},
    ]
    growth = ingest.compute_metric_growth(rows, end, window_days=5, metrics=["CALL_CLICKS"])
    assert set(growth) == {"CALL_CLICKS"}
