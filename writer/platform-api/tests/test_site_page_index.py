"""Unit tests for services.site_page_index — existing location-page detection.

No network: only the pure helpers (slugify / parse / index / match) are exercised.
"""

from __future__ import annotations

from services import site_page_index as spi


# ---------------------------------------------------------------------------
# slugify_place
# ---------------------------------------------------------------------------
def test_slugify_place_basic_and_accents():
    assert spi.slugify_place("Inner West") == "inner-west"
    assert spi.slugify_place("Los Angeles") == "los-angeles"
    assert spi.slugify_place("  St. Kilda  ") == "st-kilda"
    assert spi.slugify_place("Côte-d'Or") == "cote-d-or"
    assert spi.slugify_place("") == ""


# ---------------------------------------------------------------------------
# url_path_slugs
# ---------------------------------------------------------------------------
def test_url_path_slugs_segments_and_extension_strip():
    assert spi.url_path_slugs("https://x.com/service-areas/Inner-West/") == [
        "service-areas",
        "inner-west",
    ]
    assert spi.url_path_slugs("https://x.com/los-angeles.html") == ["los-angeles"]
    assert spi.url_path_slugs("https://x.com/") == []


# ---------------------------------------------------------------------------
# build_location_slug_index + match_site_location_page
# ---------------------------------------------------------------------------
def test_index_and_match_exact_segment_only():
    urls = [
        "https://acme.com/los-angeles/",
        "https://acme.com/service-areas/inner-west/",
        "https://acme.com/inner-west-plumber/",  # service+location — must NOT match
        "https://acme.com/blog/some-post/",
    ]
    index = spi.build_location_slug_index(urls)

    # Exact bare place-name segments match.
    assert spi.match_site_location_page("Los Angeles", index) == "https://acme.com/los-angeles/"
    assert (
        spi.match_site_location_page("Inner West", index)
        == "https://acme.com/service-areas/inner-west/"
    )
    # The bare place "Inner West" maps to the location page, NOT the
    # "inner-west-plumber" service page — matching is exact-segment, not substring.
    assert spi.match_site_location_page("Inner West", index) != (
        "https://acme.com/inner-west-plumber/"
    )
    # A place with no page is unmatched.
    assert spi.match_site_location_page("Santa Monica", index) is None


def test_match_empty_index_is_none():
    assert spi.match_site_location_page("Anywhere", {}) is None


def test_index_first_url_wins():
    urls = [
        "https://acme.com/venice/",
        "https://acme.com/areas/venice/",
    ]
    index = spi.build_location_slug_index(urls)
    assert spi.match_site_location_page("Venice", index) == "https://acme.com/venice/"


# ---------------------------------------------------------------------------
# content_tokens
# ---------------------------------------------------------------------------
def test_content_tokens_drops_generic_and_short():
    assert spi.content_tokens("Roof Restoration Melbourne") == {
        "roof",
        "restoration",
        "melbourne",
    }
    # "services"/"areas" wrappers and 1-char noise dropped.
    assert spi.content_tokens("drain-cleaning-services") == {"drain", "cleaning"}
    assert spi.content_tokens("service-areas") == set()
    assert spi.content_tokens("") == set()


# ---------------------------------------------------------------------------
# page_match_keys
# ---------------------------------------------------------------------------
def test_page_match_keys_flat_slug():
    keys = spi.page_match_keys("https://fcr.com/roof-restoration-melbourne/")
    assert frozenset({"roof", "restoration", "melbourne"}) in keys


def test_page_match_keys_nested_union_drops_generic_dirs():
    # A nested "<service>/<city>" under a generic directory still yields the full
    # content-word set via the non-generic union.
    keys = spi.page_match_keys(
        "https://fcr.com/service-areas/roof-restoration/melbourne/"
    )
    assert frozenset({"roof", "restoration", "melbourne"}) in keys


def test_page_match_keys_excludes_content_urls():
    # A blog/product/etc. URL that merely mentions the service is not a landing page.
    assert spi.page_match_keys("https://fcr.com/blog/why-roof-restoration-melbourne/") == []
    assert spi.page_match_keys("https://fcr.com/product/roof-tiles/") == []
    assert spi.page_match_keys("https://fcr.com/") == []


# ---------------------------------------------------------------------------
# build_page_token_index + match_site_page_for_keyword
# ---------------------------------------------------------------------------
def test_match_keyword_flat_service_city_page():
    # The reported bug: a published "<service> <city>" page must be detected.
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration-melbourne/"])
    assert (
        spi.match_site_page_for_keyword("roof restoration melbourne", index)
        == "https://fcr.com/roof-restoration-melbourne/"
    )


def test_match_keyword_is_word_order_insensitive():
    index = spi.build_page_token_index(["https://fcr.com/melbourne-roof-restoration/"])
    assert (
        spi.match_site_page_for_keyword("roof restoration melbourne", index)
        == "https://fcr.com/melbourne-roof-restoration/"
    )


def test_match_keyword_more_specific_page_is_distinct():
    # An emergency/commercial/sub-area variation must NOT satisfy the base page —
    # the extra distinguishing word keeps it a separate target.
    index = spi.build_page_token_index(
        [
            "https://fcr.com/emergency-roof-restoration-melbourne/",
            "https://fcr.com/roof-restoration-melbourne-cbd/",
        ]
    )
    assert spi.match_site_page_for_keyword("roof restoration melbourne", index) is None
    # But the specific variation matches its own keyword.
    assert (
        spi.match_site_page_for_keyword("emergency roof restoration melbourne", index)
        == "https://fcr.com/emergency-roof-restoration-melbourne/"
    )


def test_match_keyword_nested_service_city():
    index = spi.build_page_token_index(
        ["https://fcr.com/services/roof-restoration/melbourne/"]
    )
    assert (
        spi.match_site_page_for_keyword("roof restoration melbourne", index)
        == "https://fcr.com/services/roof-restoration/melbourne/"
    )


def test_match_keyword_ignores_generic_wrapper_words():
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration-services/"])
    assert (
        spi.match_site_page_for_keyword("roof restoration", index)
        == "https://fcr.com/roof-restoration-services/"
    )


def test_match_keyword_empty_or_no_match():
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration-melbourne/"])
    assert spi.match_site_page_for_keyword("gutter cleaning sydney", index) is None
    assert spi.match_site_page_for_keyword("services", index) is None  # all-generic
    assert spi.match_site_page_for_keyword("anything", {}) is None


def test_match_keyword_first_url_wins():
    index = spi.build_page_token_index(
        [
            "https://fcr.com/roof-restoration-melbourne/",
            "https://fcr.com/vic/roof-restoration-melbourne/",
        ]
    )
    assert (
        spi.match_site_page_for_keyword("roof restoration melbourne", index)
        == "https://fcr.com/roof-restoration-melbourne/"
    )


# ---------------------------------------------------------------------------
# match_site_service_page (national / city-less service page)
# ---------------------------------------------------------------------------
def test_match_service_page_strips_place():
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration/"])
    assert (
        spi.match_site_service_page("roof restoration melbourne", "Melbourne", index)
        == "https://fcr.com/roof-restoration/"
    )


def test_match_service_page_matches_services_wrapper_slug():
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration-services/"])
    assert (
        spi.match_site_service_page("roof restoration geelong", "Geelong", index)
        == "https://fcr.com/roof-restoration-services/"
    )


def test_match_service_page_modified_variation_not_bare_service():
    # A modified variation matches only its own national page, never the bare service.
    index = spi.build_page_token_index(
        [
            "https://fcr.com/roof-restoration/",
            "https://fcr.com/storm-damage-roof-restoration/",
        ]
    )
    assert (
        spi.match_site_service_page(
            "storm damage roof restoration melbourne", "Melbourne", index
        )
        == "https://fcr.com/storm-damage-roof-restoration/"
    )


def test_match_service_page_no_place_strip_returns_none():
    # When the place strips nothing, this is not a national match (the exact-keyword
    # matcher owns that case) — must return None so it stays a strict fallback.
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration-melbourne/"])
    assert (
        spi.match_site_service_page("roof restoration melbourne", "Sydney", index)
        is None
    )


def test_match_service_page_empty_when_no_service_or_no_page():
    index = spi.build_page_token_index(["https://fcr.com/roof-restoration/"])
    # No matching national page for a different service.
    assert spi.match_site_service_page("gutter cleaning sydney", "Sydney", index) is None
    # Keyword is only the place → nothing left to match.
    assert spi.match_site_service_page("melbourne", "Melbourne", index) is None
    assert spi.match_site_service_page("roof restoration melbourne", "Melbourne", {}) is None


# ---------------------------------------------------------------------------
# parse_robots_sitemaps
# ---------------------------------------------------------------------------
def test_parse_robots_sitemaps():
    robots = (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Sitemap: https://acme.com/sitemap.xml\n"
        "sitemap:  https://acme.com/news-sitemap.xml \n"
    )
    assert spi.parse_robots_sitemaps(robots) == [
        "https://acme.com/sitemap.xml",
        "https://acme.com/news-sitemap.xml",
    ]
    assert spi.parse_robots_sitemaps("") == []


# ---------------------------------------------------------------------------
# parse_sitemap_xml
# ---------------------------------------------------------------------------
def test_parse_sitemap_urlset():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://acme.com/los-angeles/</loc></url>
      <url><loc>https://acme.com/venice/</loc></url>
    </urlset>"""
    pages, children = spi.parse_sitemap_xml(xml)
    assert pages == ["https://acme.com/los-angeles/", "https://acme.com/venice/"]
    assert children == []


def test_parse_sitemap_index():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://acme.com/pages-sitemap.xml</loc></sitemap>
      <sitemap><loc>https://acme.com/posts-sitemap.xml</loc></sitemap>
    </sitemapindex>"""
    pages, children = spi.parse_sitemap_xml(xml)
    assert pages == []
    assert children == [
        "https://acme.com/pages-sitemap.xml",
        "https://acme.com/posts-sitemap.xml",
    ]


def test_parse_sitemap_malformed_returns_empty():
    assert spi.parse_sitemap_xml("<not xml") == ([], [])


# ---------------------------------------------------------------------------
# site_base_url
# ---------------------------------------------------------------------------
def test_site_base_url():
    assert spi.site_base_url("https://www.acme.com/about") == "https://www.acme.com"
    assert spi.site_base_url("acme.com") == "https://acme.com"
    assert spi.site_base_url("http://acme.com/x") == "http://acme.com"
    assert spi.site_base_url("") == ""
