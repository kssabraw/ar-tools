"""Unit tests for services/slug_rules — the deterministic slug/path engine.

The `SLUG_TRACES` / `PATH_TRACES` cases are copied verbatim from the Site
Architecture SOP's "Conformance Traces (URL & Slug)" section, so this file is a
live conformance check against the doc.
"""

import pytest

from services import slug_rules
from services.slug_rules import (
    RESERVED_SEGMENTS,
    apply_collision,
    build_page_path,
    build_slug,
    collision_suffix,
    compose_path,
    location_segment,
)

# ── SOP "Slug construction" conformance traces ───────────────────────────────
SLUG_TRACES = [
    ("24/7 Emergency Plumber", "24-7-emergency-plumber"),
    ("Save 50% on Heating & Cooling", "save-50-percent-on-heating-and-cooling"),
    ("How To Do SEO", "how-to-do-seo"),  # stopwords kept
    ("Best Plumber in Los Angeles (2024)", "best-plumber-in-los-angeles"),  # year stripped
    ("O'Brien's $99 Drain Special", "obriens-99-drain-special"),
    ("Commercial + Residential HVAC", "commercial-and-residential-hvac"),
    ("3.5 Ton AC Installation", "3-5-ton-ac-installation"),
]


@pytest.mark.parametrize("source,expected", SLUG_TRACES)
def test_slug_conformance_traces(source, expected):
    assert build_slug(source) == expected


# ── individual token rules ───────────────────────────────────────────────────
def test_token_table():
    assert build_slug("tv/audio") == "tv-audio"
    assert build_slug("heating & cooling") == "heating-and-cooling"
    assert build_slug("heating&cooling") == "heating-and-cooling"  # no-space still splits
    assert build_slug("55+") == "55-plus"  # + after a number
    assert build_slug("commercial + residential") == "commercial-and-residential"  # + between words
    assert build_slug("50% off") == "50-percent-off"
    assert build_slug("$99 special") == "99-special"  # drop $, keep number
    assert build_slug("#1 rated plumber") == "1-rated-plumber"
    assert build_slug("email @ us") == "email-at-us"
    assert build_slug("men's") == "mens"  # apostrophe dropped, no hyphen
    assert build_slug("men’s") == "mens"  # curly apostrophe too
    assert build_slug("72° comfort") == "72-comfort"  # degree dropped


def test_stopwords_are_kept():
    assert build_slug("The Best of Plumbing and Heating") == "the-best-of-plumbing-and-heating"


def test_casing_always_lower():
    assert build_slug("HVAC Repair NYC") == "hvac-repair-nyc"


def test_empty_source_is_empty():
    assert build_slug("") == ""
    assert build_slug("   ") == ""
    assert build_slug("///") == ""


# ── year strip ───────────────────────────────────────────────────────────────
def test_year_strip():
    assert build_slug("best plumber 2024") == "best-plumber"
    assert build_slug("2024 tax guide") == "tax-guide"
    assert build_slug("event 1999 recap") == "event-recap"
    # greedy: an in-range "year-like" number is also stripped (accepted trade-off)
    assert build_slug("2000 series pump") == "series-pump"
    # out-of-range 4-digit numbers are kept
    assert build_slug("model 3500 pump") == "model-3500-pump"
    # digits adjacent to more digits are not a "standalone year"
    assert build_slug("sku 202401 kit") == "sku-202401-kit"


# ── length cap ───────────────────────────────────────────────────────────────
def test_length_cap():
    long_source = "word " * 300  # ~1500 chars pre-slug
    out = build_slug(long_source)
    assert len(out) <= slug_rules.MAX_SLUG_LEN
    assert not out.endswith("-")


# ── deterministic collision suffix ───────────────────────────────────────────
def test_collision_suffix_is_deterministic():
    a = collision_suffix("top_level_service", "services", "/")
    b = collision_suffix("top_level_service", "services", "/")
    assert a == b  # idempotent
    assert len(a) == 5
    assert all(c in "0123456789abcdefghijklmnopqrstuvwxyz" for c in a)


def test_collision_suffix_differs_by_identity():
    a = collision_suffix("top_level_service", "services", "/")
    b = collision_suffix("blog_post", "services", "/blog")
    assert a != b


def test_apply_collision_reserved_and_taken():
    ident = ("top_level_service", "services", "/")
    # a slug hitting a reserved segment gets a stable suffix
    out = apply_collision("services", identity=ident)
    assert out.startswith("services-") and len(out) == len("services-") + 5
    assert out == apply_collision("services", identity=ident)  # same every run
    # a slug colliding with an already-taken sibling
    taken = apply_collision("landscaping", identity=ident, taken={"landscaping"})
    assert taken.startswith("landscaping-")
    # no collision -> unchanged
    assert apply_collision("landscaping", identity=ident) == "landscaping"


# ── path composition ─────────────────────────────────────────────────────────
def test_compose_path():
    assert compose_path(["los-angeles", "landscaping"]) == "/los-angeles/landscaping/"
    assert compose_path(["blog", "how-to-do-seo"]) == "/blog/how-to-do-seo/"
    assert compose_path(["/blog/", "", "post"]) == "/blog/post/"  # empties dropped, slashes cleaned
    assert compose_path(["a", "b"], trailing_slash=False) == "/a/b"


def test_location_segment_region():
    assert location_segment("Los Angeles") == "los-angeles"
    assert location_segment("Springfield", "IL") == "springfield-il"


# ── SOP "Full-path by page type" conformance traces ──────────────────────────
def test_page_path_traces():
    assert build_page_path("blog_post", keyword="How To Do SEO") == "/blog/how-to-do-seo/"
    assert (
        build_page_path("sub_service", service="Tree Trimming", subservice="Fruit Tree Trimming")
        == "/tree-trimming/fruit-tree-trimming/"
    )
    assert build_page_path("local_landing", location="Los Angeles", service="Landscaping") == "/los-angeles/landscaping/"
    assert build_page_path("product", product="BPC 157") == "/shop/bpc-157/"
    assert build_page_path("top_level_location", location="Springfield", region="IL") == "/springfield-il/"
    assert build_page_path("top_level_service", service="Tree Trimming") == "/tree-trimming/"
    assert build_page_path("neighborhood", location="Los Angeles", neighborhood="Sherman Oaks") == "/los-angeles/sherman-oaks/"


def test_page_path_unknown_type_raises():
    with pytest.raises(ValueError):
        build_page_path("mystery_page", keyword="x")


def test_reserved_segments_present():
    assert {"blog", "shop", "services", "about-us"} <= RESERVED_SEGMENTS
