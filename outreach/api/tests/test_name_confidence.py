"""Confidence scoring — the shared scale for the additional-research name sources."""

from api.services import name_confidence as nc


def test_bands():
    assert nc.band_for(90) == "high"
    assert nc.band_for(75) == "high"
    assert nc.band_for(74) == "medium"
    assert nc.band_for(50) == "medium"
    assert nc.band_for(49) == "low"


# --- site scrape (deterministic) --------------------------------------------------------------


def test_jsonld_founder_on_multiple_pages_is_high():
    c = nc.score_site_scrape(source_kind="jsonld", title="Founder", page_count=2)
    assert c.score == 100 and c.band == "high"  # 65 + 12 + 18 + 5


def test_single_page_role_anchored_manager_is_medium_or_low():
    c = nc.score_site_scrape(source_kind="text", title="Manager", page_count=1)
    assert c.score == 50 and c.band == "medium"  # 45 + 0 + 0 + 5


def test_structured_data_beats_text():
    a = nc.score_site_scrape(source_kind="jsonld", title="Owner", page_count=1)
    b = nc.score_site_scrape(source_kind="text", title="Owner", page_count=1)
    assert a.score > b.score


def test_multi_page_corroboration_raises_confidence():
    one = nc.score_site_scrape(source_kind="text", title="Owner", page_count=1)
    two = nc.score_site_scrape(source_kind="text", title="Owner", page_count=2)
    assert two.score == one.score + 18


# --- web search (blended) ---------------------------------------------------------------------


def test_single_citation_no_model_is_low():
    c = nc.score_web_search(model_confidence=None, citations=["https://a.com/x"])
    assert c.score == 40 and c.band == "low"


def test_multiple_distinct_domains_corroborate():
    one = nc.score_web_search(citations=["https://a.com/x"])
    three = nc.score_web_search(citations=["https://a.com/x", "https://b.com/y", "https://c.com/z"])
    assert three.score == one.score + 20


def test_a_citation_on_the_business_own_domain_adds_trust():
    c = nc.score_web_search(citations=["https://acme.com/about"], business_website="https://acme.com")
    base = nc.score_web_search(citations=["https://other.com/about"], business_website="https://acme.com")
    assert c.score == base.score + 10


def test_model_self_rating_moves_but_does_not_set_the_score():
    # deterministic backbone 40 (1 citation); a confident model lifts it, but not to its own value.
    low_model = nc.score_web_search(model_confidence=10, citations=["https://a.com/x"])
    high_model = nc.score_web_search(model_confidence=90, citations=["https://a.com/x"])
    assert low_model.score < high_model.score
    # 0.65*40 + 0.35*90 = 57.5 → 58, not 90 (the deterministic backbone caps the model's influence)
    assert high_model.score == 58


def test_distinct_domains_dedups_www_and_paths():
    assert nc.distinct_citation_domains(
        ["https://www.a.com/1", "https://a.com/2", "http://b.com"]) == 2


def test_factors_are_recorded_for_replay():
    c = nc.score_web_search(model_confidence=80, citations=["https://a.com", "https://b.com"],
                            business_website="https://a.com")
    assert c.factors["distinct_domains"] == 2
    assert c.factors["business_domain_cited"] is True
    assert c.factors["model_confidence"] == 80
