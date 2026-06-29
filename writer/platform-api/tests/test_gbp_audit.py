"""Unit tests for the GBP profile audit pure helper (no network)."""

from __future__ import annotations

from services import gbp_audit


def _full_gbp(**over):
    g = {
        "gbp_category": "Plumber",
        "description": "We are a long-established plumbing business serving the whole metro area.",
        "website": "https://ace.com",
        "phone": "123",
        "photo": "p.jpg",
        "hours": {"mon": "9-5"},
        "gbp_categories": ["Plumber", "Drainage service"],
        "gbp_review_count": 200,
    }
    g.update(over)
    return g


def test_audit_full_profile_scores_100_no_gaps():
    out = gbp_audit.audit(_full_gbp(), [])
    assert out["score"] == 100
    assert out["gaps"] == []
    assert out["review_gap"] is None


def test_audit_flags_missing_fields():
    out = gbp_audit.audit(_full_gbp(website="", hours=None, description="short"), [])
    labels = {c["label"] for c in out["checks"] if not c["ok"]}
    assert "Website linked" in labels
    assert "Opening hours" in labels
    assert "Business description" in labels
    assert out["score"] < 100
    assert "Website linked" in out["gaps"]


def test_audit_review_gap_vs_competitor_median():
    competitors = [
        {"review_count": 100, "primary_category": "Plumber"},
        {"review_count": 300, "primary_category": "Plumber"},
        {"review_count": 500, "primary_category": "Plumber"},
    ]
    out = gbp_audit.audit(_full_gbp(gbp_review_count=120), competitors)
    assert out["review_gap"] is not None
    assert out["review_gap"]["competitor_median"] == 300
    assert out["review_gap"]["deficit"] == 180


def test_audit_category_gaps_from_majority_of_competitors():
    competitors = [
        {"primary_category": "Plumber", "gbp_categories": ["Emergency plumber", "Drainage service"]},
        {"primary_category": "Plumber", "gbp_categories": ["Emergency plumber"]},
        {"primary_category": "Plumber", "gbp_categories": ["Gas fitter"]},
    ]
    # Client lacks "emergency plumber" (on 2/3 competitors → >= half).
    out = gbp_audit.audit(_full_gbp(gbp_categories=["Plumber"]), competitors)
    assert "emergency plumber" in out["category_gaps"]
    assert "gas fitter" not in out["category_gaps"]  # only 1/3 competitors


def test_audit_empty_gbp_low_score():
    out = gbp_audit.audit({}, [])
    assert out["score"] == 0
    assert "Website linked" in out["gaps"]
