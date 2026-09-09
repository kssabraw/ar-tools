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
    # A long, cleanly-written description with no captured category and no
    # address/service areas: the keyword + location signals have nothing to check
    # against, so they must be skipped rather than false-flagged. The copy carries
    # no superlatives, filler, stuffing, or fluff opening, so nothing else fires.
    long_clean = (
        "Our team installs and services residential heating and cooling systems, "
        "handles seasonal tune-ups, and replaces aging equipment for households "
        "throughout the region, scheduling each visit at a time that fits around the "
        "customer's day and leaving the work area tidy when the job is finished."
    )
    out = gbp_audit.audit(
        {"description": long_clean, "gbp_category": "", "gbp_categories": []},
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


# --- SOP writing-quality trip-wires (stuffing / superlatives / filler / opening) ---

def test_description_quality_flags_city_stuffing():
    # Names the service (roofing) and the city (Anaheim) so only stuffing fires:
    # "Anaheim" is repeated four times.
    desc = (
        "Anaheim Roofing is a roofing contractor in Anaheim. Our Anaheim team handles "
        "roof repair and roof replacement across Anaheim for homeowners and businesses "
        "that want dependable roofing work done right the first time, every time."
    )
    out = gbp_audit.audit(
        _full_gbp(description=desc, gbp_category="Roofing contractor",
                  address="1 Main St, Anaheim, CA 92805"),
        [],
    )
    issues = out["description_quality"]["issues"]
    assert "keyword_stuffed" in issues
    assert "too_short" not in issues and "missing_location" not in issues


def test_description_quality_natural_breadth_not_flagged_as_stuffing():
    # The SOP's model roofing description: rich service breadth, city named only
    # twice — must NOT be flagged as stuffing (guards the threshold).
    good = (
        "ABC Roofing is a residential and commercial roofing contractor serving "
        "Anaheim and communities throughout Orange County. Our team specializes in "
        "roof replacement, roof repair, leak detection, roof inspections, tile "
        "roofing, shingle roofing, and flat roofing systems. We serve Anaheim, "
        "Fullerton, Orange, and surrounding Orange County communities."
    )
    out = gbp_audit.audit(
        _full_gbp(description=good, gbp_category="Roofing contractor",
                  address="1 Main St, Anaheim, CA 92805"),
        [],
    )
    assert out["description_quality"]["issues"] == []


def test_description_quality_flags_superlatives():
    desc = (
        "Ace Plumber is the best plumber in Fort Lauderdale with guaranteed same-day "
        "service for homeowners and businesses across the area, handling leak repair, "
        "drain cleaning, repipes and water heater installation with upfront pricing."
    )
    out = gbp_audit.audit(
        _full_gbp(description=desc, gbp_category="Plumber",
                  address="1 Main St, Fort Lauderdale, FL 33301"),
        [],
    )
    assert "promotional_superlatives" in out["description_quality"]["issues"]


def test_description_quality_flags_marketing_filler():
    desc = (
        "Ace Plumber serves Fort Lauderdale homeowners and businesses with leak "
        "repair, drain cleaning and water heater installation. We pride ourselves on "
        "quality and treat every customer like family, because your satisfaction is "
        "our number one priority."
    )
    out = gbp_audit.audit(
        _full_gbp(description=desc, gbp_category="Plumber",
                  address="1 Main St, Fort Lauderdale, FL 33301"),
        [],
    )
    assert "marketing_filler" in out["description_quality"]["issues"]


def test_description_quality_flags_generic_opening():
    desc = (
        "Welcome to Ace Plumber, serving Fort Lauderdale homeowners and businesses "
        "with leak repair, drain cleaning, repipes and water heater installation "
        "across the area for over twenty years with upfront pricing."
    )
    out = gbp_audit.audit(
        _full_gbp(description=desc, gbp_category="Plumber",
                  address="1 Main St, Fort Lauderdale, FL 33301"),
        [],
    )
    assert "generic_opening" in out["description_quality"]["issues"]


# --- the pure SOP detectors ---

def test_find_superlatives():
    assert gbp_audit.find_superlatives("We are the best, guaranteed.")
    assert gbp_audit.find_superlatives("We repair roofs across Tampa.") == []


def test_find_marketing_filler():
    assert gbp_audit.find_marketing_filler("We pride ourselves on quality.")
    assert gbp_audit.find_marketing_filler("Customer satisfaction is our top priority.")
    assert gbp_audit.find_marketing_filler("We repipe homes across the metro.") == []


def test_has_generic_opening():
    assert gbp_audit.has_generic_opening("Welcome to Ace Plumber, serving Tampa.")
    assert gbp_audit.has_generic_opening("Looking for a plumber you can trust?")
    assert gbp_audit.has_generic_opening("Ace Plumber is a plumber serving Tampa.") is False


def test_overused_terms():
    text = "Anaheim roofing in Anaheim by Anaheim pros for Anaheim homes."
    assert gbp_audit.overused_terms(text, {"anaheim", "roofing"}) == ["anaheim"]
    assert gbp_audit.overused_terms("Serving Anaheim and Orange County.", {"anaheim"}) == []
