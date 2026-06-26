"""Unit tests for the sitemap fetcher (pure helpers + robots discovery).

Network I/O (`_fetch_bytes`/`fetch_sitemap_urls` against a live host) isn't
exercised; `_discover_sitemaps` is tested with `_fetch_bytes` mocked.
"""

from __future__ import annotations

import asyncio
import gzip
from unittest.mock import AsyncMock, patch

from services import sitemap


# ── _base_url ─────────────────────────────────────────────────────────────────

def test_base_url_normalizes_origin():
    assert sitemap._base_url("acme.com") == "https://acme.com"
    assert sitemap._base_url("http://x.com/some/path?q=1") == "http://x.com"
    assert sitemap._base_url("  https://Y.com  ") == "https://Y.com"
    assert sitemap._base_url("") is None
    assert sitemap._base_url("   ") is None


# ── _parse ────────────────────────────────────────────────────────────────────

def test_parse_urlset_from_bytes():
    body = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://a.com/x</loc></url>"
        b"<url><loc>https://a.com/y</loc></url></urlset>"
    )
    assert sitemap._parse(body) == ("urlset", ["https://a.com/x", "https://a.com/y"])


def test_parse_sitemapindex():
    body = (
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<sitemap><loc>https://a.com/s1.xml</loc></sitemap></sitemapindex>"
    )
    assert sitemap._parse(body) == ("index", ["https://a.com/s1.xml"])


def test_parse_garbage_is_empty():
    assert sitemap._parse(b"not xml at all") == ("", [])
    assert sitemap._parse(b"<html><body>nope</body></html>") == ("", [])


# ── _sitemap_body / _gunzip (gzip handling — #3, #4) ──────────────────────────

def test_sitemap_body_passes_plain_through():
    # A `.gz` URL whose body the transport already decoded arrives as plain XML
    # (no gzip magic bytes) — it must be parsed, not double-inflated (#3).
    plain = b"<urlset></urlset>"
    assert sitemap._sitemap_body(plain) == plain


def test_sitemap_body_inflates_real_gzip():
    raw = gzip.compress(b"<urlset></urlset>")
    assert raw[:2] == b"\x1f\x8b"
    assert sitemap._sitemap_body(raw) == b"<urlset></urlset>"


def test_gunzip_bomb_is_capped():
    # A small gzip that expands to 50MB must inflate to at most _MAX_BYTES, not
    # the full payload (#4 — bounded decompression).
    raw = gzip.compress(b"A" * (50 * 1024 * 1024))
    assert len(raw) < 1 * 1024 * 1024  # tiny compressed
    out = sitemap._gunzip(raw)
    assert out is not None
    assert len(out) <= sitemap._MAX_BYTES


def test_gunzip_rejects_non_gzip():
    assert sitemap._gunzip(b"<urlset></urlset>") is None


# ── _discover_sitemaps (robots.txt — #5 relative, #6 spacing) ─────────────────

def _discover(robots: bytes | None, base: str = "https://acme.com") -> list[str]:
    async def go():
        with patch.object(sitemap, "_fetch_bytes", new=AsyncMock(return_value=robots)):
            return await sitemap._discover_sitemaps(object(), base)
    return asyncio.run(go())


def test_discover_resolves_relative_and_tolerates_spacing():
    robots = (
        b"User-agent: *\n"
        b"Sitemap : /sitemap_index.xml\n"        # relative + space before colon (#5,#6)
        b"sitemap: https://cdn.example/extra.xml\n"  # absolute, lowercase
    )
    got = _discover(robots)
    assert got == ["https://acme.com/sitemap_index.xml", "https://cdn.example/extra.xml"]


def test_discover_falls_back_to_default_paths():
    got = _discover(None)  # no robots.txt
    assert got[0] == "https://acme.com/sitemap.xml"
    assert "https://acme.com/wp-sitemap.xml" in got
    assert "https://acme.com/sitemap_index.xml.gz" in got


def test_discover_falls_back_when_robots_has_no_sitemap_line():
    got = _discover(b"User-agent: *\nDisallow: /private\n")
    assert got == [f"https://acme.com{p}" for p in sitemap._DEFAULT_SITEMAP_PATHS]
