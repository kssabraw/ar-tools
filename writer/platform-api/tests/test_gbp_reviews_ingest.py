"""Unit tests for the v4 reviews period-windowing helpers (pure)."""

from __future__ import annotations

from services import gbp_reviews_ingest as gr


def test_review_date():
    assert gr.review_date("2026-07-15T12:34:56.789Z") == "2026-07-15"
    assert gr.review_date("2026-07-15") == "2026-07-15"
    assert gr.review_date("2026/07/15") is None  # wrong separators
    assert gr.review_date("short") is None
    assert gr.review_date("") is None
    assert gr.review_date(None) is None


def test_in_period_inclusive():
    assert gr.in_period("2026-07-01T00:00:00Z", "2026-07-01", "2026-07-31") is True
    assert gr.in_period("2026-07-31T23:59:59Z", "2026-07-01", "2026-07-31") is True
    assert gr.in_period("2026-06-30T23:59:59Z", "2026-07-01", "2026-07-31") is False
    assert gr.in_period("2026-08-01T00:00:00Z", "2026-07-01", "2026-07-31") is False
    assert gr.in_period("", "2026-07-01", "2026-07-31") is False


def test_summarize_period():
    reviews = [
        {"create_time": "2026-07-05T10:00:00Z", "rating": 5},
        {"create_time": "2026-07-20T10:00:00Z", "rating": 3},
        {"create_time": "2026-07-10T10:00:00Z", "rating": None},   # in period, unrated
        {"create_time": "2026-06-25T10:00:00Z", "rating": 5},       # before period
        {"create_time": "2026-08-02T10:00:00Z", "rating": 1},       # after period
    ]
    out = gr.summarize_period(reviews, "2026-07-01", "2026-07-31")
    assert out["count"] == 3
    # newest-first ordering
    assert [r["create_time"][:10] for r in out["items"]] == ["2026-07-20", "2026-07-10", "2026-07-05"]
    # average over rated-in-period only: (5 + 3) / 2
    assert out["average_rating"] == 4.0


def test_summarize_period_none_rated():
    reviews = [{"create_time": "2026-07-05T10:00:00Z", "rating": None}]
    out = gr.summarize_period(reviews, "2026-07-01", "2026-07-31")
    assert out["count"] == 1 and out["average_rating"] is None


def test_summarize_period_empty():
    out = gr.summarize_period([], "2026-07-01", "2026-07-31")
    assert out == {"count": 0, "average_rating": None, "items": []}
