"""Unit tests for services.local_seo_precheck — pure matching/dedup helpers.

No network: only the pure helpers (token normalize / keyword match / URL key) are
exercised. The orchestration (detect_existing_pages) hits Supabase + nlp +
DataForSEO/GSC and is covered by integration testing, not here.
"""

from __future__ import annotations

from services import local_seo_precheck as p


# ---------------------------------------------------------------------------
# normalize_tokens
# ---------------------------------------------------------------------------
def test_normalize_tokens_singularizes_and_drops_stopwords():
    assert p.normalize_tokens("Emergency Plumbers") == frozenset({"emergency", "plumber"})
    assert p.normalize_tokens("roof restoration in the Melbourne") == frozenset(
        {"roof", "restoration", "melbourne"}
    )
    # Short words and -ss endings aren't over-singularized.
    assert "gas" in p.normalize_tokens("gas heater")
    assert "glass" in p.normalize_tokens("glass repair")
    assert p.normalize_tokens("") == frozenset()


# ---------------------------------------------------------------------------
# keywords_match
# ---------------------------------------------------------------------------
def test_keywords_match_close_variants():
    assert p.keywords_match("emergency plumber melbourne", "Melbourne Emergency Plumbers")
    assert p.keywords_match("roof restoration melbourne", "Roof Restoration, Melbourne")
    assert p.keywords_match("roof restoration melbourne", "melbourne roof restoration")


def test_keywords_match_rejects_different_topics():
    assert not p.keywords_match("roof restoration melbourne", "roof repair melbourne")
    assert not p.keywords_match("emergency plumber melbourne", "emergency plumber sydney")
    # An empty keyword never matches (no signal).
    assert not p.keywords_match("", "anything")
    assert not p.keywords_match("anything", "")


# ---------------------------------------------------------------------------
# canonical_url_key
# ---------------------------------------------------------------------------
def test_canonical_url_key_normalizes():
    assert p.canonical_url_key("https://www.X.com/Roof/") == p.canonical_url_key("http://x.com/roof")
    assert p.canonical_url_key("https://x.com/a?b=1#c") == "x.com/a"
    assert p.canonical_url_key("x.com/path/") == "x.com/path"
    assert p.canonical_url_key("") == ""
    assert p.canonical_url_key(None) == ""


# ---------------------------------------------------------------------------
# _ranking_queries — geo-modified term ("<service> <city>")
# ---------------------------------------------------------------------------
def test_ranking_queries_attaches_city():
    assert p._ranking_queries("roof restoration", "Melbourne,Victoria,Australia") == [
        "roof restoration Melbourne"
    ]


def test_ranking_queries_no_double_city_when_already_in_keyword():
    assert p._ranking_queries("roof restoration melbourne", "Melbourne,Victoria,Australia") == [
        "roof restoration melbourne"
    ]


def test_ranking_queries_falls_back_to_bare_when_no_city():
    assert p._ranking_queries("plumber", "") == ["plumber"]
    assert p._ranking_queries("", "Melbourne") == []


# ---------------------------------------------------------------------------
# _build_variants
# ---------------------------------------------------------------------------
def test_build_variants_trims_and_drops_empty():
    assert p._build_variants("  roof restoration melbourne  ") == ["roof restoration melbourne"]
    assert p._build_variants("") == []
    assert p._build_variants("   ") == []
