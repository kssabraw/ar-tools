"""Unit tests for services.brand_analysis — pure response-analysis helpers."""

from __future__ import annotations

from services import brand_analysis as ba


# ── domain helpers ────────────────────────────────────────────────────────────
def test_extract_host_strips_scheme_and_www():
    assert ba.extract_host("https://www.Acme.com/contact") == "acme.com"
    assert ba.extract_host("acme.com") == "acme.com"
    assert ba.extract_host("") == ""


def test_domains_match_is_subdomain_tolerant():
    assert ba.domains_match("https://blog.acme.com/x", "acme.com")
    assert ba.domains_match("acme.com", "www.acme.com")
    assert not ba.domains_match("acme.com", "acmeplumbing.com")


def test_classify_source_type():
    assert ba.classify_source_type("https://www.yelp.com/biz/x") == "directory"
    assert ba.classify_source_type("trustpilot.com") == "review"
    assert ba.classify_source_type("facebook.com") == "social"
    assert ba.classify_source_type("reddit.com") == "forum"
    assert ba.classify_source_type("google.com") == "search"
    assert ba.classify_source_type("someplumber.com") == "editorial"


# ── source analysis ───────────────────────────────────────────────────────────
def test_analyze_sources_flags_client_and_types():
    out = ba.analyze_sources(
        ["https://yelp.com/biz/acme", "https://www.acme.com/", "https://yelp.com/biz/acme"],
        client_domain="acme.com",
        competitor_domains=["rival.com"],
    )
    assert out["client_cited"] is True
    assert out["by_type"] == {"directory": 1, "editorial": 1}  # dup yelp collapsed
    assert any(d["is_client"] for d in out["domains"])
    assert out["competitor_only_sources"] == []  # client IS cited → empty


def test_analyze_sources_competitor_only_sources_when_client_absent():
    out = ba.analyze_sources(
        ["https://directory.com/rival", "https://rival.com/"],
        client_domain="acme.com",
        competitor_domains=["rival.com"],
    )
    assert out["client_cited"] is False
    assert "rival.com" in out["competitor_only_sources"]


# ── AIO mention kind ──────────────────────────────────────────────────────────
def test_aio_mention_kind_all_cases():
    assert ba.aio_mention_kind("acme.com", ["acme.com"], ["other.com"]) == "in_content_link"
    assert ba.aio_mention_kind("acme.com", ["other.com"], ["acme.com"]) == "citation_only"
    assert ba.aio_mention_kind("acme.com", ["acme.com"], ["acme.com"]) == "both"
    assert ba.aio_mention_kind("acme.com", ["x.com"], ["y.com"]) == "none"
    assert ba.aio_mention_kind("", [], []) == "none"
    # Subdomain tolerance.
    assert ba.aio_mention_kind("acme.com", ["www.acme.com"], []) == "in_content_link"


# ── discovered competitors / attributes ───────────────────────────────────────
def test_derive_discovered_competitors_excludes_brand_and_tracked():
    businesses = [
        {"name": "Acme Plumbing Co", "attributes": ["24/7"]},     # brand (fuzzy)
        {"name": "Rival Drains", "attributes": ["cheap"]},         # tracked
        {"name": "New Co", "attributes": ["fast", "licensed"]},    # discovered
        {"name": "New Co"},                                        # dup
    ]
    out = ba.derive_discovered_competitors(businesses, brand="Acme Plumbing", tracked_names=["Rival Drains"])
    assert [b["name"] for b in out] == ["New Co"]
    assert out[0]["attributes"] == ["fast", "licensed"]


def test_competitor_attributes_skips_brand_and_attrless():
    businesses = [
        {"name": "Acme", "attributes": ["best"]},   # brand → skip
        {"name": "Rival", "attributes": ["24/7", "family-owned"]},
        {"name": "NoAttrs", "attributes": []},       # skip (no attributes)
    ]
    out = ba.competitor_attributes(businesses, brand="Acme")
    assert out == [{"name": "Rival", "attributes": ["24/7", "family-owned"]}]


# ── brand-fact accuracy ───────────────────────────────────────────────────────
def test_diff_brand_facts_flags_phone_mismatch_and_closed():
    flags = ba.diff_brand_facts(
        {"phone": "(02) 9000 1234", "permanently_closed": True},
        {"phone": "02 9000 9999", "gbp_rating": 4.6, "gbp_review_count": 10},
    )
    fields = {f["field"] for f in flags}
    assert "phone" in fields and "status" in fields


def test_diff_brand_facts_no_false_positive_on_matching_phone():
    flags = ba.diff_brand_facts(
        {"phone": "+61 2 9000 1234"},
        {"phone": "(02) 9000 1234", "gbp_rating": 4.6},
    )
    assert flags == []  # same last 7 digits


def test_diff_brand_facts_empty_when_no_data():
    assert ba.diff_brand_facts(None, {"phone": "123"}) == []
    assert ba.diff_brand_facts({"phone": "123"}, None) == []


# ── assembly ──────────────────────────────────────────────────────────────────
def test_build_response_analysis_assembles_and_includes_aio_for_aio_engines():
    rich = {
        "mention_rank": 0, "total_businesses": 3, "prominence": "none",
        "businesses": [
            {"name": "Rival", "attributes": ["24/7"]},
            {"name": "Other", "attributes": ["cheap"]},
        ],
        "inferred_intent": "emergency plumbing", "mentioned_locations": ["Sydney"],
        "stated_brand_facts": None,
    }
    out = ba.build_response_analysis(
        rich=rich, citations=["https://yelp.com/x"], client_domain="acme.com",
        competitor_domains=["rival.com"], tracked_competitor_names=["Rival"],
        brand="Acme", gbp={"phone": "123"}, aio_inline_domains=["acme.com"],
        aio_reference_domains=[], is_aio=True,
    )
    assert out["position"] == {"rank": None, "total_businesses": 3}
    assert out["intent"]["inferred"] == "emergency plumbing"
    assert out["aio"]["mention_kind"] == "in_content_link"
    # "Rival" is tracked → not discovered; "Other" is discovered.
    assert [b["name"] for b in out["discovered_competitors"]] == ["Other"]


def test_build_response_analysis_omits_aio_for_non_aio_engines():
    out = ba.build_response_analysis(
        rich=None, citations=[], client_domain="acme.com", competitor_domains=[],
        tracked_competitor_names=[], brand="Acme", is_aio=False,
    )
    assert "aio" not in out
    assert out["position"]["rank"] is None


# ── consensus ─────────────────────────────────────────────────────────────────
def test_consensus_rollup_counts_engines_per_business():
    rows = [
        {"status": "completed", "engine": "chatgpt", "response_analysis": {
            "competitor_attributes": [{"name": "Rival", "attributes": ["24/7"]}],
            "discovered_competitors": [{"name": "New Co", "attributes": []}],
        }},
        {"status": "completed", "engine": "claude", "response_analysis": {
            "competitor_attributes": [{"name": "Rival", "attributes": ["family-owned"]}],
            "discovered_competitors": [],
        }},
        {"status": "failed", "engine": "gemini", "response_analysis": {}},  # skipped
    ]
    out = ba.consensus_rollup(rows, brand="Acme")
    assert out["engines_total"] == 2
    top = out["businesses"][0]
    assert top["name"] == "Rival" and top["count"] == 2
    assert set(top["attributes"]) == {"24/7", "family-owned"}
