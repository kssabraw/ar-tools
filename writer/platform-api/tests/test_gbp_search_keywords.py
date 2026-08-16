"""Unit tests for the GBP search-keywords pure helpers."""

from __future__ import annotations

from datetime import date

from services import gbp_performance_service as gbp
from services import gbp_search_keywords as skw


def test_recent_complete_months():
    assert skw.recent_complete_months(date(2026, 8, 15), 3) == [
        date(2026, 7, 1), date(2026, 6, 1), date(2026, 5, 1),
    ]


def test_recent_complete_months_year_boundary():
    assert skw.recent_complete_months(date(2026, 1, 10), 2) == [date(2025, 12, 1), date(2025, 11, 1)]


def test_aggregate_keywords_sums_and_sorts():
    rows = [
        {"keyword": "plumber", "value": 100, "is_threshold": False},
        {"keyword": "plumber", "value": 20, "is_threshold": True},  # same kw, another location
        {"keyword": "emergency plumber", "value": 50, "is_threshold": False},
        {"keyword": "drain", "value": 5, "is_threshold": True},  # all-threshold
    ]
    items, total = skw.aggregate_keywords(rows, limit=10)
    assert items[0] == {"keyword": "plumber", "value": 120, "is_threshold": False}
    assert {"keyword": "drain", "value": 5, "is_threshold": True} in items
    assert total == 175
    assert [i["keyword"] for i in items] == ["plumber", "emergency plumber", "drain"]


def test_aggregate_keywords_limit():
    rows = [{"keyword": f"k{i}", "value": i, "is_threshold": False} for i in range(30)]
    items, _ = skw.aggregate_keywords(rows, limit=5)
    assert len(items) == 5 and items[0]["keyword"] == "k29"


def test_sum_by_keyword():
    rows = [
        {"keyword": "plumber", "value": 100},
        {"keyword": "plumber", "value": 20},   # another location/month
        {"keyword": "drain", "value": 5},
        {"keyword": "", "value": 9},            # no keyword → skipped
        {"value": 3},                            # missing keyword → skipped
    ]
    assert skw.sum_by_keyword(rows) == {"plumber": 120, "drain": 5}
    assert skw.sum_by_keyword([]) == {}


def test_parse_search_keywords():
    payload = {"searchKeywordsCounts": [
        {"searchKeyword": "plumber", "insightsValue": {"value": "340"}},
        {"searchKeyword": "drain cleaning", "insightsValue": {"threshold": "15"}},
        {"searchKeyword": "", "insightsValue": {"value": "5"}},  # dropped — no keyword
    ]}
    assert gbp.parse_search_keywords(payload) == [
        {"keyword": "plumber", "value": 340, "is_threshold": False},
        {"keyword": "drain cleaning", "value": 15, "is_threshold": True},
    ]


def test_parse_search_keywords_empty():
    assert gbp.parse_search_keywords({}) == []
