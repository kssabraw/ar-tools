"""Unit tests for services.gbp_reviews — the pure review-period helpers."""

from __future__ import annotations

from datetime import date

from services import gbp_reviews as gr


def test_query_for_prefers_maps_uri_then_falls_back():
    assert gr.query_for({"google_maps_uri": "u", "place_id": "p", "business_name": "n"}) == "u"
    assert gr.query_for({"place_id": "p", "business_name": "n"}) == "p"
    assert gr.query_for({"business_name": "n"}) == "n"
    assert gr.query_for({}) is None
    assert gr.query_for(None) is None


def test_parse_reviews_maps_sorts_and_drops_undated():
    place = {"reviews_data": [
        {"review_datetime_utc": "2026-07-01 10:00:00", "review_rating": 5, "review_text": "great", "author_title": "A"},
        {"review_datetime_utc": "2026-08-05 09:00:00", "review_rating": 3, "review_text": "meh", "author_title": "B"},
        {"review_rating": 4, "review_text": "no date"},  # dropped (no date)
        "junk",
    ]}
    out = gr.parse_reviews(place)
    assert [r["date"] for r in out] == [date(2026, 8, 5), date(2026, 7, 1)]  # newest first
    assert out[0]["rating"] == 3.0 and out[1]["text"] == "great"
    assert gr.parse_reviews({}) == [] and gr.parse_reviews({"reviews_data": None}) == []


def _reviews():
    return [
        {"date": date(2026, 8, 5), "rating": 5.0, "text": "Fantastic team", "reviewer": "A"},
        {"date": date(2026, 8, 1), "rating": 4.0, "text": "Solid support", "reviewer": "B"},
        {"date": date(2026, 7, 20), "rating": 2.0, "text": "Not happy", "reviewer": "C"},
        {"date": date(2026, 6, 15), "rating": 5.0, "text": "Old but good", "reviewer": "D"},
    ]


def test_count_in_range_is_half_open():
    # this period (2026-07-11, 2026-08-10]: 08-05, 08-01 and 07-20
    assert gr.count_in_range(_reviews(), date(2026, 7, 11), date(2026, 8, 10)) == 3
    # previous period (2026-06-11, 2026-07-11]: the 06-15 review
    assert gr.count_in_range(_reviews(), date(2026, 6, 11), date(2026, 7, 11)) == 1
    assert gr.count_in_range([], date(2026, 1, 1), date(2026, 2, 1)) == 0


def test_avg_rating_asof():
    # on/before 2026-07-20: ratings 2.0 (07-20) and 5.0 (06-15) → 3.5
    assert gr.avg_rating_asof(_reviews(), date(2026, 7, 20)) == 3.5
    assert gr.avg_rating_asof(_reviews(), date(2026, 5, 1)) is None  # nothing that early


def test_newest_highlights_positive_in_range_only():
    hl = gr.newest_highlights(_reviews(), date(2026, 7, 11), date(2026, 8, 10), min_rating=4.0, limit=2)
    assert hl == ["Fantastic team", "Solid support"]  # newest first, the 2.0 excluded
    # the 5.0 on 06-15 is out of range
    assert gr.newest_highlights(_reviews(), date(2026, 8, 6), date(2026, 8, 10)) == []
