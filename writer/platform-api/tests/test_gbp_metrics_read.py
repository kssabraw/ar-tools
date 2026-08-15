"""Unit tests for the GBP reporting-dashboard read/aggregation helpers.

No network / no DB: fold_metric / fold_rows, build_growth_cards (ordering +
impression folding), last_data_date, and build_series (dense zero-fill +
trailing-lag trim). The router's paginated DB read is integration-tested.
"""

from __future__ import annotations

from datetime import date

from services import gbp_metrics_read as read


# ----------------------------------------------------------------------------
# fold_metric / fold_rows
# ----------------------------------------------------------------------------
def test_fold_metric_collapses_impressions():
    for m in read.IMPRESSION_METRICS:
        assert read.fold_metric(m) == "profile_views"


def test_fold_metric_passes_engagement_through():
    assert read.fold_metric("CALL_CLICKS") == "CALL_CLICKS"
    assert read.fold_metric("WEBSITE_CLICKS") == "WEBSITE_CLICKS"


def test_fold_rows_rewrites_metric_only():
    rows = [{"date": "2026-08-01", "metric": "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "value": 5}]
    folded = read.fold_rows(rows)
    assert folded[0]["metric"] == "profile_views"
    assert folded[0]["value"] == 5
    assert folded[0]["date"] == "2026-08-01"


# ----------------------------------------------------------------------------
# build_growth_cards
# ----------------------------------------------------------------------------
def _daily(days, metric, value, start):
    return [
        {"date": (date.fromordinal(start.toordinal() + i)).isoformat(), "metric": metric, "value": value}
        for i in range(days)
    ]


def test_build_growth_cards_folds_and_orders():
    end = date(2026, 8, 10)
    window = 5
    cur_start = date(2026, 8, 6)  # end - 4
    prev_start = date(2026, 8, 1)  # cur_start - 5
    rows = []
    # Two impression sub-types in the current window → fold into profile_views.
    rows += _daily(5, "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", 10, cur_start)
    rows += _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 10, cur_start)
    # Calls in current + prior window.
    rows += _daily(5, "CALL_CLICKS", 2, cur_start)
    rows += _daily(5, "CALL_CLICKS", 1, prev_start)

    cards = read.build_growth_cards(rows, end, window)
    by_metric = {c["metric"]: c for c in cards}

    # profile_views = 5 days * (10 + 10) = 100 this window, 0 prior.
    assert by_metric["profile_views"]["current"] == 100
    assert by_metric["profile_views"]["previous"] == 0
    assert by_metric["profile_views"]["pct"] is None  # prior zero → None
    # calls = 10 this window, 5 prior → +100%.
    assert by_metric["CALL_CLICKS"]["current"] == 10
    assert by_metric["CALL_CLICKS"]["previous"] == 5
    assert by_metric["CALL_CLICKS"]["pct"] == 100.0

    # Display order preserved (profile_views before CALL_CLICKS), unseen metrics omitted.
    assert [c["metric"] for c in cards] == ["profile_views", "CALL_CLICKS"]
    assert by_metric["profile_views"]["label"] == "Profile views"


def test_build_growth_cards_empty_input():
    assert read.build_growth_cards([], date(2026, 8, 10), 30) == []


# ----------------------------------------------------------------------------
# last_data_date / build_series
# ----------------------------------------------------------------------------
def test_last_data_date():
    rows = [
        {"date": "2026-08-01", "metric": "CALL_CLICKS", "value": 1},
        {"date": "2026-08-05", "metric": "CALL_CLICKS", "value": 1},
        {"date": "2026-08-03", "metric": "WEBSITE_CLICKS", "value": 1},
    ]
    assert read.last_data_date(rows) == date(2026, 8, 5)
    assert read.last_data_date([]) is None


def test_build_series_dense_zero_fill():
    start, end = date(2026, 8, 1), date(2026, 8, 4)
    rows = [
        {"date": "2026-08-01", "metric": "CALL_CLICKS", "value": 3},
        {"date": "2026-08-04", "metric": "WEBSITE_CLICKS", "value": 7},
    ]
    series = read.build_series(rows, start, end)
    # One point per day across the full range (dense).
    assert [p["date"] for p in series] == ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
    # Every point carries every dashboard metric key.
    assert set(series[0]["values"].keys()) == {
        "profile_views", "CALL_CLICKS", "WEBSITE_CLICKS",
        "BUSINESS_DIRECTION_REQUESTS", "BUSINESS_CONVERSATIONS",
    }
    assert series[0]["values"]["CALL_CLICKS"] == 3
    assert series[1]["values"]["CALL_CLICKS"] == 0  # zero-filled gap day
    assert series[3]["values"]["WEBSITE_CLICKS"] == 7


def test_build_series_trims_trailing_lag():
    # Requested window ends 08-10 but data only reaches 08-06 → series stops there
    # (no phantom zeros for the not-yet-arrived tail).
    start, end = date(2026, 8, 1), date(2026, 8, 10)
    rows = [{"date": "2026-08-06", "metric": "CALL_CLICKS", "value": 2}]
    series = read.build_series(rows, start, end)
    assert series[-1]["date"] == "2026-08-06"
    assert series[-1]["values"]["CALL_CLICKS"] == 2


def test_build_series_folds_impressions_into_profile_views():
    start = end = date(2026, 8, 6)
    rows = [
        {"date": "2026-08-06", "metric": "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "value": 4},
        {"date": "2026-08-06", "metric": "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "value": 6},
    ]
    series = read.build_series(rows, start, end)
    assert series[0]["values"]["profile_views"] == 10


def test_build_series_empty_when_no_data():
    assert read.build_series([], date(2026, 8, 1), date(2026, 8, 10)) == []


# ----------------------------------------------------------------------------
# groups / breakdown / actions / insights
# ----------------------------------------------------------------------------
_CS = date(2026, 8, 6)   # current window start (end 2026-08-10, window 5)
_END = date(2026, 8, 10)
_W = 5


def test_group_tag_on_cards():
    rows = _daily(5, "CALL_CLICKS", 2, _CS) + _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 20, _CS)
    groups = {c["metric"]: c["group"] for c in read.build_growth_cards(rows, _END, _W)}
    assert groups["profile_views"] == "visibility"
    assert groups["CALL_CLICKS"] == "actions"


def test_build_breakdown_surface_device_share():
    rows = (
        _daily(5, "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", 10, _CS)
        + _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 20, _CS)
        + _daily(5, "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", 5, _CS)
        + _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_MAPS", 15, _CS)
    )
    bd = read.build_breakdown(rows, _END, _W)
    surf = {r["label"]: r for r in bd["surface"]}
    assert surf["Search"]["current"] == 150 and surf["Maps"]["current"] == 100
    assert surf["Search"]["share"] == 60.0 and surf["Maps"]["share"] == 40.0
    dev = {r["label"]: r for r in bd["device"]}
    assert dev["Desktop"]["current"] == 75 and dev["Mobile"]["current"] == 175
    assert dev["Mobile"]["share"] == 70.0


def test_build_actions_summary_engagement():
    rows = (
        _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 50, _CS)  # 250 views
        + _daily(5, "CALL_CLICKS", 2, _CS)
        + _daily(5, "WEBSITE_CLICKS", 4, _CS)
        + _daily(5, "BUSINESS_DIRECTION_REQUESTS", 1, _CS)  # 35 actions
    )
    a = read.build_actions_summary(rows, _END, _W)
    assert a["current"] == 35
    assert a["engagement_current"] == 14.0  # 35 / 250


def test_build_insights_sentences_and_empty():
    rows = _daily(5, "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 50, _CS) + _daily(5, "CALL_CLICKS", 2, _CS)
    cards = read.build_growth_cards(rows, _END, _W)
    lines = read.build_insights(cards, read.build_breakdown(rows, _END, _W), read.build_actions_summary(rows, _END, _W))
    assert lines and any("profile was seen" in ln for ln in lines)
    assert read.build_insights([], {"surface": [], "device": []}, {"current": 0, "previous": 0}) == []


# ----------------------------------------------------------------------------
# reviews / csv export
# ----------------------------------------------------------------------------
def test_build_reviews():
    gbp = {
        "gbp_rating": "4.8", "gbp_review_count": "77",
        "reviews": [{"reviewer": "Jane", "rating": 5, "text": "Great!", "date": "2026-08-01"}, "Loved it"],
    }
    r = read.build_reviews(gbp)
    assert r["rating"] == 4.8 and r["review_count"] == 77
    assert r["items"][0] == {"reviewer": "Jane", "rating": 5, "text": "Great!", "date": "2026-08-01"}
    assert r["items"][1]["text"] == "Loved it"


def test_build_reviews_empty():
    assert read.build_reviews(None) == {"rating": None, "review_count": 0, "items": []}
    r = read.build_reviews({"gbp_rating": None, "gbp_review_count": None})
    assert r["rating"] is None and r["review_count"] == 0 and r["items"] == []


def test_csv_rows():
    series = [{"date": "2026-08-06", "values": {
        "profile_views": 100, "CALL_CLICKS": 3, "WEBSITE_CLICKS": 5,
        "BUSINESS_DIRECTION_REQUESTS": 2, "BUSINESS_CONVERSATIONS": 0}}]
    rows = read.csv_rows(series)
    assert rows[0] == ["Date", "Profile views", "Calls", "Website clicks", "Direction requests", "Messages"]
    assert rows[1] == ["2026-08-06", 100, 3, 5, 2, 0]
