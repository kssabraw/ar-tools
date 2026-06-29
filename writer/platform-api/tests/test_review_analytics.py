"""Unit tests for review analytics pure helpers (no network)."""

from __future__ import annotations

from datetime import date

from services import review_analytics

TODAY = date(2026, 6, 29)


def _rev(rating, d):
    return {"rating": rating, "date": d}


def test_analyze_reviews_distribution_velocity_negatives():
    reviews = [
        _rev(5, "2026-06-01"), _rev(5, "2026-05-01"), _rev(4, "2026-04-01"),
        _rev(1, "2026-06-15"),                         # recent negative (<=2, within 90d)
        _rev(2, "2024-01-01"),                         # old negative — not "recent", not in velocity year
    ]
    a = review_analytics.analyze_reviews(reviews, TODAY)
    assert a["count"] == 5
    assert a["rating_distribution"]["5"] == 2 and a["rating_distribution"]["1"] == 1
    assert a["recent_negatives"] == 1                  # only the 2026-06-15 one-star
    assert a["velocity_per_month"] == round(4 / 12, 1)  # 4 reviews within the last year
    assert a["last_review_date"] == "2026-06-15"
    assert a["avg_rating"] == round((5 + 5 + 4 + 1 + 2) / 5, 2)


def test_analyze_reviews_empty():
    a = review_analytics.analyze_reviews([], TODAY)
    assert a["count"] == 0 and a["avg_rating"] is None and a["velocity_per_month"] == 0


def test_compare_velocity_behind_median():
    client = {"velocity_per_month": 1.0, "avg_rating": 4.5}
    competitors = [
        {"velocity_per_month": 3.0, "avg_rating": 4.6},
        {"velocity_per_month": 5.0, "avg_rating": 4.8},
        {"velocity_per_month": 4.0, "avg_rating": 4.7},
    ]
    cmp = review_analytics.compare(client, competitors)
    assert cmp["competitor_median_velocity"] == 4.0
    assert cmp["velocity_behind"] == 3.0       # 4.0 − 1.0


def test_compare_not_behind_when_client_leads():
    client = {"velocity_per_month": 9.0, "avg_rating": 4.9}
    competitors = [{"velocity_per_month": 3.0, "avg_rating": 4.5}]
    cmp = review_analytics.compare(client, competitors)
    assert cmp["velocity_behind"] is None


def test_detect_review_gap_on_velocity_or_negatives():
    cmp = {"competitor_median_velocity": 4.0, "velocity_behind": 3.0}
    client = {"velocity_per_month": 1.0, "recent_negatives": 0}
    gap = review_analytics.detect_review_gap(cmp, client, min_behind=2.0)
    assert gap is not None and gap["behind"] == 3.0

    # Below the velocity threshold AND no negatives → no signal.
    cmp2 = {"competitor_median_velocity": 2.0, "velocity_behind": 1.0}
    assert review_analytics.detect_review_gap(cmp2, {"recent_negatives": 0}, 2.0) is None

    # Recent negatives alone trigger it even if velocity is fine.
    assert review_analytics.detect_review_gap(
        {"velocity_behind": None}, {"velocity_per_month": 8, "recent_negatives": 2}, 2.0
    ) is not None
