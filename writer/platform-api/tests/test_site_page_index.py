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
