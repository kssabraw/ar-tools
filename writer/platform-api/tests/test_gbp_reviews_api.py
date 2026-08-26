"""Unit tests for the GBP v4 reviews parser + classifier (pure helpers)."""

from __future__ import annotations

from services import gbp_reviews_api as rv


def test_star_to_int():
    assert rv.star_to_int("FIVE") == 5
    assert rv.star_to_int("ONE") == 1
    assert rv.star_to_int("STAR_RATING_UNSPECIFIED") is None
    assert rv.star_to_int(None) is None


def test_parse_review_full():
    item = {
        "reviewId": "abc123",
        "reviewer": {"displayName": "Jane Doe"},
        "starRating": "FOUR",
        "comment": "Great work!",
        "createTime": "2026-07-15T12:34:56.789Z",
        "updateTime": "2026-07-16T00:00:00Z",
        "reviewReply": {"comment": "Thanks!"},
    }
    assert rv.parse_review(item) == {
        "review_id": "abc123",
        "reviewer": "Jane Doe",
        "rating": 4,
        "text": "Great work!",
        "create_time": "2026-07-15T12:34:56.789Z",
        "update_time": "2026-07-16T00:00:00Z",
        "has_reply": True,
    }


def test_parse_review_id_falls_back_to_name_tail():
    item = {"name": "accounts/1/locations/2/reviews/xyz789", "starRating": "FIVE"}
    out = rv.parse_review(item)
    assert out["review_id"] == "xyz789"
    assert out["rating"] == 5
    assert out["has_reply"] is False
    assert out["reviewer"] == "" and out["text"] == ""


def test_parse_reviews_drops_idless():
    payload = {"reviews": [
        {"reviewId": "a", "starRating": "FIVE"},
        {"starRating": "THREE"},  # no id and no name → dropped
        {"name": "x/reviews/b", "starRating": "TWO"},
    ]}
    ids = [r["review_id"] for r in rv.parse_reviews(payload)]
    assert ids == ["a", "b"]


def test_parse_reviews_empty():
    assert rv.parse_reviews({}) == []


def test_classify_review_error():
    assert rv.classify_review_error(403, "Google My Business API has not been used") == "gbp_api_not_enabled"
    assert rv.classify_review_error(429, "RESOURCE_EXHAUSTED") == "gbp_quota_not_granted"
    assert rv.classify_review_error(403, "forbidden") == "account_not_a_manager_or_forbidden"
    assert rv.classify_review_error(401, "") == "account_not_a_manager_or_forbidden"
    assert rv.classify_review_error(404, "") == "location_not_found"
    assert rv.classify_review_error(500, "boom") == "http_500"
    assert rv.classify_review_error(None, "") == "unknown_error"
