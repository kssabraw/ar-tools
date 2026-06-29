"""Unit tests for Local Relevance Scorecard pure helpers (no network)."""

from __future__ import annotations

from services import local_relevance as lr


def test_service_terms_strip_location_and_canonicalize():
    loc = lr.location_terms("Chatswood, New South Wales")
    svc = lr.service_terms("emergency plumber chatswood", loc)
    assert "plumber" in svc          # canonical rep of plumber/plumbing/plumbers
    assert "emergency" in svc
    assert "chatswood" not in svc     # location stripped from the service
    assert "the" not in svc           # stopword removed


def test_mentions_uses_synonyms_and_word_boundaries():
    svc = lr.service_terms("plumber", set())
    assert lr.mentions("Great plumbing work, fixed our leak", svc) is True   # plumbing ≈ plumber
    assert lr.mentions("They did roofing for us", svc) is False
    assert lr.mentions("", svc) is False


def test_reviews_mention_stats():
    svc = lr.service_terms("plumber", set())
    loc = lr.location_terms("Chatswood")
    reviews = [
        "Best plumber in Chatswood, fixed my pipes",   # service + location
        "Quick plumbing repair",                        # service only
        "Lovely staff, very friendly",                  # neither
    ]
    stats = lr.reviews_mention_stats(reviews, svc, loc)
    assert stats["reviews_total"] == 3
    assert stats["reviews_service_mentions"] == 2
    assert stats["reviews_location_mentions"] == 1


def test_category_match_levels():
    svc = lr.service_terms("emergency plumber", set())
    assert lr.category_match("Plumber", svc) == "related"        # overlaps on plumber, not 'emergency'
    assert lr.category_match("Emergency plumbing service", svc) == "exact"  # both service tokens present
    assert lr.category_match("Roofing contractor", svc) == "none"
    assert lr.category_match(None, svc) == "none"


def test_page_relevance():
    svc = lr.service_terms("plumber", set())
    loc = lr.location_terms("Chatswood")
    rel = lr.page_relevance("Chatswood Plumbing — burst pipes & blocked drains", svc, loc)
    assert rel["service"] is True and rel["location"] is True
    rel2 = lr.page_relevance("Welcome to our homepage", svc, loc)
    assert rel2["service"] is False and rel2["location"] is False


def test_extract_page_text_includes_title():
    html = "<html><head><title>Chatswood Plumber</title></head><body><h1>Burst pipe repair</h1></body></html>"
    text = lr.extract_page_text(html)
    assert "Chatswood Plumber" in text and "Burst pipe repair" in text


def test_derive_location_prefers_tracking_then_address():
    assert lr.derive_location({"rank_tracking_location": "Chatswood, NSW"}) == "Chatswood, NSW"
    addr = lr.derive_location({"gbp": {"address": "12 Help St, Chatswood NSW 2067, Australia"}})
    assert "Chatswood" in addr and "Australia" not in addr


def test_detect_relevance_gaps_flags_client_weaknesses():
    scorecard = {
        "keyword": "plumber",
        "client": {
            "is_client": True, "category_match": "none",
            "page_service_relevant": False,
            "reviews_total": 5, "reviews_service_mentions": 0,
            "domain_rating": 10, "page_ur": 5,
        },
        "competitors": [
            {"category_match": "exact", "domain_rating": 40, "page_ur": 30},
            {"category_match": "related", "domain_rating": 35, "page_ur": 25},
        ],
    }
    gap = lr.detect_relevance_gaps(scorecard)
    assert gap is not None
    joined = " | ".join(gap["gaps"])
    assert "category" in joined
    assert "isn't about the service" in joined
    assert "reviews mention the service" in joined
    assert "DR" in joined and "UR" in joined


def test_detect_relevance_gaps_none_when_clean():
    scorecard = {
        "keyword": "plumber",
        "client": {"category_match": "exact", "page_service_relevant": True,
                   "reviews_total": 5, "reviews_service_mentions": 4, "domain_rating": 50, "page_ur": 40},
        "competitors": [{"category_match": "exact", "domain_rating": 45, "page_ur": 35}],
    }
    assert lr.detect_relevance_gaps(scorecard) is None
