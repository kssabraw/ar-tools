"""Unit tests for the Keyword Research seed-suggestion pure logic (no I/O)."""

from services import keyword_research_seeds as krs


# --- is_local -----------------------------------------------------------------
def test_is_local_by_gbp_presence():
    assert krs.is_local({"gbp": {"gbp_category": "Plumber"}})
    assert not krs.is_local({"gbp": None})
    assert not krs.is_local({})


# --- build_seed_context -------------------------------------------------------
def test_build_seed_context_local():
    ctx = krs.build_seed_context({
        "name": "Acme Plumbing",
        "gbp": {"gbp_category": "Plumber", "address": "123 Main St, Austin, TX"},
        "website_url": "https://www.acmeplumbing.com/",
    })
    assert "Acme Plumbing" in ctx
    assert "Plumber" in ctx
    assert "Austin" in ctx
    assert "acmeplumbing.com" in ctx  # www stripped


def test_build_seed_context_empty_client_is_blank():
    assert krs.build_seed_context({}) == ""


# --- _city_of -----------------------------------------------------------------
def test_city_of_street_address():
    assert krs._city_of("123 Main St, Austin, TX") == "Austin"


def test_city_of_city_state():
    assert krs._city_of("Austin, TX") == "Austin"


def test_city_of_bare_and_empty():
    assert krs._city_of("Sydney") == "Sydney"
    assert krs._city_of("") == ""
    assert krs._city_of(None) == ""


# --- clean_seeds --------------------------------------------------------------
def test_clean_seeds_drops_near_me_brand_and_dupes():
    out = krs.clean_seeds(
        ["Acme Plumbing", "emergency plumber", "emergency plumber near me",
         "Emergency Plumber", "drain cleaning", ""],
        "Acme Plumbing",
    )
    assert "emergency plumber" in out
    assert "drain cleaning" in out
    assert "Acme Plumbing" not in out               # pure brand-name seed dropped
    assert "emergency plumber near me" not in out    # near-me dropped
    # Case-insensitive dedupe: only one "emergency plumber".
    assert sum(1 for s in out if s.lower() == "emergency plumber") == 1


def test_clean_seeds_excludes_already_researched():
    existing = {krs.keyword_research.normalize_keyword("roof repair")}
    out = krs.clean_seeds(["roof repair", "gutter cleaning"], "Acme Roofing", existing)
    assert out == ["gutter cleaning"]


def test_clean_seeds_respects_cap():
    out = krs.clean_seeds([f"service {i}" for i in range(20)], None, cap=5)
    assert len(out) == 5


# --- fallback_seeds -----------------------------------------------------------
def test_fallback_seeds_pairs_category_with_city():
    seeds = krs.fallback_seeds({
        "name": "Acme Plumbing",
        "gbp": {"gbp_category": "Plumber", "address": "123 Main St, Austin, TX"},
    })
    assert "Plumber" in seeds
    assert "Plumber Austin" in seeds


def test_fallback_seeds_no_gbp_is_empty():
    assert krs.fallback_seeds({"name": "Acme"}) == []
