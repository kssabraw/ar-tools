"""Unit tests for the GA4 reporting connector (Client Reporting Phase 2).

The GA4 REST API and Supabase are fully mocked — nothing hits the network or a
DB. Covers the pure helpers in services/ga4_service.py and services/ga4_ingest.py.
"""

from __future__ import annotations

from datetime import date

import pytest

from services import ga4_ingest, ga4_service


# ---------------------------------------------------------------------------
# normalize_property_id
# ---------------------------------------------------------------------------
def test_normalize_property_id_accepts_full_form():
    assert ga4_service.normalize_property_id("properties/123456789") == "properties/123456789"


def test_normalize_property_id_accepts_bare_numeric():
    assert ga4_service.normalize_property_id("123456789") == "properties/123456789"


def test_normalize_property_id_strips_whitespace():
    assert ga4_service.normalize_property_id("  987  ") == "properties/987"


@pytest.mark.parametrize("bad", ["", "   ", "acme.com", "properties/", "properties/abc", "G-123", "properties/12a"])
def test_normalize_property_id_rejects_junk(bad):
    with pytest.raises(ValueError):
        ga4_service.normalize_property_id(bad)


# ---------------------------------------------------------------------------
# parse_report_rows
# ---------------------------------------------------------------------------
def test_parse_report_rows_dimension_and_metrics():
    resp = {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}],
        "rows": [
            {"dimensionValues": [{"value": "20260814"}], "metricValues": [{"value": "120"}, {"value": "95"}]},
            {"dimensionValues": [{"value": "20260815"}], "metricValues": [{"value": "80"}, {"value": "60"}]},
        ],
    }
    rows = ga4_service.parse_report_rows(resp)
    assert rows == [
        {"date": "20260814", "sessions": 120.0, "totalUsers": 95.0},
        {"date": "20260815", "sessions": 80.0, "totalUsers": 60.0},
    ]


def test_parse_report_rows_no_dimension():
    resp = {
        "metricHeaders": [{"name": "sessions"}],
        "rows": [{"metricValues": [{"value": "7"}]}],
    }
    rows = ga4_service.parse_report_rows(resp)
    assert rows == [{"sessions": 7.0}]


def test_parse_report_rows_empty_is_empty():
    assert ga4_service.parse_report_rows({}) == []


def test_parse_report_rows_bad_metric_value_coerces_zero():
    resp = {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": [{"name": "sessions"}],
        "rows": [{"dimensionValues": [{"value": "20260814"}], "metricValues": [{"value": None}]}],
    }
    rows = ga4_service.parse_report_rows(resp)
    assert rows[0]["sessions"] == 0.0


# ---------------------------------------------------------------------------
# _iso_date
# ---------------------------------------------------------------------------
def test_iso_date_converts_ga_format():
    assert ga4_service._iso_date("20260814") == "2026-08-14"


@pytest.mark.parametrize("bad", [None, "", "2026-08-14", "2026081", "abcdefgh"])
def test_iso_date_rejects_bad(bad):
    assert ga4_service._iso_date(bad) is None


# ---------------------------------------------------------------------------
# classify_access_error
# ---------------------------------------------------------------------------
def test_classify_api_not_enabled():
    v = ga4_service.classify_access_error(403, "Analytics Data API has not been used in project 123")
    assert v.status == "error"
    assert v.detail == "ga4_api_not_enabled"


def test_classify_forbidden_is_no_access():
    v = ga4_service.classify_access_error(403, "permission denied")
    assert v.status == "no_access"


def test_classify_unauthorized_is_no_access():
    assert ga4_service.classify_access_error(401).status == "no_access"


def test_classify_not_found_is_no_access():
    assert ga4_service.classify_access_error(404).status == "no_access"


def test_classify_rate_limited_is_error():
    v = ga4_service.classify_access_error(429)
    assert v.status == "error" and v.detail == "rate_limited"


def test_classify_unknown_is_error():
    assert ga4_service.classify_access_error(None).status == "error"


# ---------------------------------------------------------------------------
# ga4_ingest.compute_window
# ---------------------------------------------------------------------------
def test_compute_window_three_days_inclusive():
    start, end = ga4_ingest.compute_window(date(2026, 8, 15), 3)
    assert start == "2026-08-13"
    assert end == "2026-08-15"


def test_compute_window_single_day_floor():
    start, end = ga4_ingest.compute_window(date(2026, 8, 15), 0)
    assert start == "2026-08-15"
    assert end == "2026-08-15"


# ---------------------------------------------------------------------------
# ga4_ingest.to_records
# ---------------------------------------------------------------------------
def test_to_records_maps_fields():
    daily = [
        {
            "date": "2026-08-14",
            "sessions": 120,
            "total_users": 95,
            "screen_page_views": 300,
            "conversions": 4,
            "channels": {"Organic Search": 80, "Direct": 40},
        }
    ]
    recs = ga4_ingest.to_records("prop-uuid", daily)
    assert recs == [
        {
            "property_id": "prop-uuid",
            "date": "2026-08-14",
            "sessions": 120,
            "total_users": 95,
            "screen_page_views": 300,
            "conversions": 4,
            "channels": {"Organic Search": 80, "Direct": 40},
        }
    ]


def test_to_records_null_conversions_preserved():
    daily = [{"date": "2026-08-14", "sessions": 10, "conversions": None}]
    recs = ga4_ingest.to_records("p", daily)
    assert recs[0]["conversions"] is None
    assert recs[0]["channels"] == {}


def test_to_records_skips_dateless_rows():
    daily = [{"sessions": 10}, {"date": "2026-08-14", "sessions": 5}]
    recs = ga4_ingest.to_records("p", daily)
    assert len(recs) == 1
    assert recs[0]["date"] == "2026-08-14"


# ---------------------------------------------------------------------------
# fetch_daily_metrics — conversions fallback + channel folding (run_report mocked)
# ---------------------------------------------------------------------------
def test_fetch_daily_metrics_folds_channels(monkeypatch):
    def fake_run_report(property_id, start, end, metrics, dimensions=None):
        if dimensions == ["date"]:
            return [
                {"date": "20260814", "sessions": 120.0, "totalUsers": 95.0,
                 "screenPageViews": 300.0, "keyEvents": 4.0},
            ]
        if dimensions == ["date", ga4_service.CHANNEL_DIMENSION]:
            return [
                {"date": "20260814", ga4_service.CHANNEL_DIMENSION: "Organic Search", "sessions": 80.0},
                {"date": "20260814", ga4_service.CHANNEL_DIMENSION: "Direct", "sessions": 40.0},
            ]
        return []

    monkeypatch.setattr(ga4_service, "run_report", fake_run_report)
    out = ga4_service.fetch_daily_metrics("properties/1", "2026-08-14", "2026-08-14")
    assert len(out) == 1
    row = out[0]
    assert row["date"] == "2026-08-14"
    assert row["sessions"] == 120
    assert row["conversions"] == 4
    assert row["channels"] == {"Organic Search": 80, "Direct": 40}


def test_fetch_daily_metrics_falls_back_to_legacy_conversions_name(monkeypatch):
    # keyEvents 400s; the legacy "conversions" metric is accepted → conversions
    # still reported (from the legacy field).
    seen = []

    def fake_run_report(property_id, start, end, metrics, dimensions=None):
        if dimensions == ["date"]:
            seen.append(tuple(metrics))
            if ga4_service.CONVERSION_METRIC in metrics:
                raise ga4_service.Ga4ApiError(400, "field keyEvents is not a valid metric")
            # legacy name present → return a row carrying "conversions"
            return [{"date": "20260814", "sessions": 10.0, "totalUsers": 8.0,
                     "screenPageViews": 20.0, "conversions": 2.0}]
        return []

    monkeypatch.setattr(ga4_service, "run_report", fake_run_report)
    out = ga4_service.fetch_daily_metrics("properties/1", "2026-08-14", "2026-08-14")
    assert ga4_service.CONVERSION_METRIC_LEGACY in seen[-1]  # legacy attempt made
    assert out[0]["conversions"] == 2
    assert out[0]["sessions"] == 10


def test_fetch_daily_metrics_drops_conversions_when_both_names_rejected(monkeypatch):
    calls = {"n": 0}

    def fake_run_report(property_id, start, end, metrics, dimensions=None):
        if dimensions == ["date"] and (
            ga4_service.CONVERSION_METRIC in metrics
            or ga4_service.CONVERSION_METRIC_LEGACY in metrics
        ):
            calls["n"] += 1
            raise ga4_service.Ga4ApiError(400, "unknown metric")
        if dimensions == ["date"]:  # core-metrics-only retry
            return [{"date": "20260814", "sessions": 10.0, "totalUsers": 8.0, "screenPageViews": 20.0}]
        return []

    monkeypatch.setattr(ga4_service, "run_report", fake_run_report)
    out = ga4_service.fetch_daily_metrics("properties/1", "2026-08-14", "2026-08-14")
    assert calls["n"] == 2  # both keyEvents and conversions attempted
    assert out[0]["conversions"] is None
    assert out[0]["sessions"] == 10


def test_run_report_paginates_on_row_count(monkeypatch):
    monkeypatch.setattr(ga4_service, "_PAGE_SIZE", 2)
    offsets = []
    all_rows = [
        {"dimensionValues": [{"value": f"2026080{i}"}], "metricValues": [{"value": str(i)}]}
        for i in range(1, 4)  # 3 rows total, page size 2 → two pages
    ]

    def fake_post(url, body):
        offsets.append(body["offset"])
        page = all_rows[body["offset"]: body["offset"] + body["limit"]]
        return {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": page,
            "rowCount": len(all_rows),
        }

    monkeypatch.setattr(ga4_service, "_post", fake_post)
    rows = ga4_service.run_report("properties/1", "2026-08-01", "2026-08-03", ["sessions"], ["date"])
    assert len(rows) == 3
    assert offsets == [0, 2]  # paged twice, no third empty call


def test_run_report_single_page_no_extra_call(monkeypatch):
    monkeypatch.setattr(ga4_service, "_PAGE_SIZE", 100)
    calls = {"n": 0}

    def fake_post(url, body):
        calls["n"] += 1
        return {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [{"dimensionValues": [{"value": "20260801"}], "metricValues": [{"value": "5"}]}],
            "rowCount": 1,
        }

    monkeypatch.setattr(ga4_service, "_post", fake_post)
    rows = ga4_service.run_report("properties/1", "2026-08-01", "2026-08-01", ["sessions"], ["date"])
    assert len(rows) == 1 and calls["n"] == 1


def test_fetch_daily_metrics_reraises_non_400(monkeypatch):
    def fake_run_report(property_id, start, end, metrics, dimensions=None):
        raise ga4_service.Ga4ApiError(403, "permission denied")

    monkeypatch.setattr(ga4_service, "run_report", fake_run_report)
    with pytest.raises(ga4_service.Ga4ApiError):
        ga4_service.fetch_daily_metrics("properties/1", "2026-08-14", "2026-08-14")


# ---------------------------------------------------------------------------
# verify_property_access — classification via mocked run_report
# ---------------------------------------------------------------------------
def test_verify_ok(monkeypatch):
    monkeypatch.setattr(ga4_service, "run_report", lambda *a, **k: [])
    assert ga4_service.verify_property_access("123").status == "ok"


def test_verify_no_access(monkeypatch):
    def boom(*a, **k):
        raise ga4_service.Ga4ApiError(403, "caller does not have permission")

    monkeypatch.setattr(ga4_service, "run_report", boom)
    assert ga4_service.verify_property_access("123").status == "no_access"


def test_verify_rejects_bad_property_without_calling(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("run_report should not be called for an invalid id")

    monkeypatch.setattr(ga4_service, "run_report", boom)
    v = ga4_service.verify_property_access("not-a-property")
    assert v.status == "error"
