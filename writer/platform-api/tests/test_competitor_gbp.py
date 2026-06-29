"""Unit tests for competitor GBP intelligence pure helpers (no network)."""

from __future__ import annotations

from services import competitor_gbp


def test_select_competitors_aggregates_across_keywords_and_ranks():
    results = [
        {"competitors": [
            {"place_id": "a", "name": "Ace", "primary_category": "Plumber", "rating": 4.5, "reviews": 100,
             "website": "ace.com", "found_pins": 10, "top3_pins": 6},
            {"place_id": "b", "name": "Bob", "found_pins": 8, "top3_pins": 2},
        ]},
        {"competitors": [
            {"place_id": "a", "name": "Ace", "found_pins": 5, "top3_pins": 4},
        ]},
    ]
    out = competitor_gbp.select_competitors(results, max_n=10)
    assert [c["place_id"] for c in out] == ["a", "b"]   # Ace ranks first (top3 10 vs 2)
    ace = out[0]
    assert ace["found_pins"] == 15 and ace["top3_pins"] == 10
    assert ace["primary_category"] == "Plumber" and ace["rating"] == 4.5


def test_select_competitors_caps_and_skips_blank_place_id():
    results = [{"competitors": [
        {"place_id": None, "top3_pins": 99},   # skipped
        {"place_id": "a", "top3_pins": 3},
        {"place_id": "b", "top3_pins": 2},
        {"place_id": "c", "top3_pins": 1},
    ]}]
    out = competitor_gbp.select_competitors(results, max_n=2)
    assert [c["place_id"] for c in out] == ["a", "b"]


def test_profile_row_maps_gbp_details_with_leaderboard_context():
    comp = {"place_id": "a", "name": "Ace", "found_pins": 10, "top3_pins": 6, "reviews": 90}
    details = {
        "place_id": "a",
        "gbp": {
            "business_name": "Ace Plumbing",
            "gbp_category": "Plumber",
            "gbp_categories": ["Plumber", "Drainage"],
            "gbp_rating": 4.6,
            "gbp_review_count": 102,
            "website": "ace.com",
            "phone": "123",
            "address": "1 St",
            "photo": "p.jpg",
            "hours": {"mon": "9-5"},
        },
    }
    row = competitor_gbp.profile_row("client-1", comp, details)
    assert row["client_id"] == "client-1"
    assert row["place_id"] == "a"
    assert row["name"] == "Ace Plumbing"
    assert row["gbp_categories"] == ["Plumber", "Drainage"]
    assert row["review_count"] == 102           # GBP detail wins over leaderboard
    assert row["has_hours"] is True
    assert row["found_pins"] == 10 and row["top3_pins"] == 6
    assert row["profile"]["business_name"] == "Ace Plumbing"


def test_profile_row_falls_back_to_leaderboard_when_gbp_sparse():
    comp = {"place_id": "b", "name": "Bob", "primary_category": "Roofer", "reviews": 12, "website": "b.com"}
    row = competitor_gbp.profile_row("c", comp, {"gbp": {}})
    assert row["name"] == "Bob"
    assert row["primary_category"] == "Roofer"
    assert row["review_count"] == 12
    assert row["website"] == "b.com"
    assert row["has_hours"] is False
