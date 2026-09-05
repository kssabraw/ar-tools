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


# --- description quality (the strategist-loop trigger, separate from completeness) ---


def test_description_quality_ok_for_strong_description():
    strong = (
        "Ace Plumber has served Fort Lauderdale homeowners and businesses for over "
        "twenty years, handling everything from emergency leak repair and blocked "
        "drains to full repipes and water heater installation, with upfront pricing "
        "and same-day service you can rely on."
    )
    out = gbp_audit.audit(
        _full_gbp(
            description=strong,
            gbp_category="Plumber",
            address="1 Main St, Fort Lauderdale, FL 33301",
        ),
        [],
    )
    dq = out["description_quality"]
    assert dq["ok"] is True
    assert dq["issues"] == []
    assert dq["length"] == len(strong)


def test_description_quality_flags_short_missing_keyword_and_location():
    out = gbp_audit.audit(
        _full_gbp(
            description="We do great work.",
            gbp_category="Plumber",
            gbp_categories=["Plumber", "Drainage service"],
            address="1 Main St, Fort Lauderdale, FL 33301",
        ),
        [],
    )
    dq = out["description_quality"]
    assert dq["ok"] is False
    assert set(dq["issues"]) == {"too_short", "missing_service_keyword", "missing_location"}
    # The completeness check still passes (present, >= 50 chars is a separate floor)...
    assert "Business description" not in out["gaps"] or dq["length"] < 50


def test_description_quality_best_effort_skips_absent_inputs():
    # A long description with no captured category and no address/service areas:
    # the keyword + location signals have nothing to check against, so they must
    # be skipped rather than false-flagged. Only length can be judged.
    long_generic = (
        "We are a family-owned local business that has proudly served our community "
        "for many years, always putting our customers first and standing behind every "
        "job we complete with a satisfaction guarantee and friendly, reliable help."
    )
    out = gbp_audit.audit(
        {"description": long_generic, "gbp_category": "", "gbp_categories": []},
        [],
    )
    dq = out["description_quality"]
    assert dq["issues"] == []
    assert dq["ok"] is True


def test_description_quality_missing_description():
    out = gbp_audit.audit({"description": ""}, [])
    dq = out["description_quality"]
    assert dq["ok"] is False
    assert dq["length"] == 0
    assert dq["issues"] == []


def test_description_quality_location_matched_despite_trailing_country():
    # A trailing ", USA" must not hide the city: the description names Fort
    # Lauderdale, so missing_location must NOT fire.
    strong = (
        "Ace Plumber has served Fort Lauderdale homeowners for over twenty years, "
        "handling emergency leak repair, blocked drains, repipes and water heater "
        "installation with upfront pricing and same-day service you can rely on."
    )
    out = gbp_audit.audit(
        _full_gbp(
            description=strong,
            gbp_category="Plumber",
            address="1 Main St, Fort Lauderdale, FL 33301, USA",
        ),
        [],
    )
    assert "missing_location" not in out["description_quality"]["issues"]


def test_description_quality_too_short_only_when_keyword_and_location_present():
    # Short but names the service (plumber) and the city (Lauderdale) → only too_short.
    out = gbp_audit.audit(
        _full_gbp(
            description="Trusted Lauderdale plumber.",
            gbp_category="Plumber",
            address="1 Main St, Fort Lauderdale, FL 33301",
        ),
        [],
    )
    dq = out["description_quality"]
    assert dq["issues"] == ["too_short"]
    assert dq["ok"] is False
