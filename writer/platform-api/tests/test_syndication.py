"""Unit tests for the Content Syndication pure helpers.

No network/DB: only the deterministic helpers (content-type classification, the
included-types resolver, the rewrite title split, and the Doc/Sheet builders) are
exercised. The orchestration (scan_client / the job handlers) hits Supabase +
ScrapeOwl + Anthropic + the Apps Script and is covered by integration testing.
"""

from __future__ import annotations

from services import syndication_discovery as disco
from services import syndication_publish as pub
from services import syndication_rewrite as rew


# ---------------------------------------------------------------------------
# classify_content_type
# ---------------------------------------------------------------------------
def test_classify_products():
    assert disco.classify_content_type("https://x.com/product/widget") == "product"
    assert disco.classify_content_type("https://x.com/products/widget") == "product"
    assert disco.classify_content_type("https://x.com/shop/item-5") == "product"
    # Sitemap-name signal wins even when the path is generic.
    assert disco.classify_content_type("https://x.com/widget", "product-sitemap.xml") == "product"


def test_classify_blog_posts():
    assert disco.classify_content_type("https://x.com/blog/my-post") == "blog_post"
    assert disco.classify_content_type("https://x.com/news/update") == "blog_post"
    assert disco.classify_content_type("https://x.com/2024/05/a-story") == "blog_post"
    assert disco.classify_content_type("https://x.com/anything", "post-sitemap.xml") == "blog_post"


def test_classify_pages_default():
    assert disco.classify_content_type("https://x.com/about") == "page"
    assert disco.classify_content_type("https://x.com/") == "page"
    assert disco.classify_content_type("https://x.com/services/roofing") == "page"


def test_product_beats_blog_when_both_hint():
    # A product URL that also sits under /blog-ish naming still classifies product
    # (product is checked first — a store URL is never a blog post).
    assert disco.classify_content_type("https://x.com/product/news-stand") == "product"


# ---------------------------------------------------------------------------
# _included_types
# ---------------------------------------------------------------------------
def test_included_types_defaults_to_all():
    assert disco._included_types({}) == {"blog_post", "page", "product"}


def test_included_types_respects_toggles():
    cfg = {"include_blog": True, "include_pages": False, "include_products": False}
    assert disco._included_types(cfg) == {"blog_post"}


# ---------------------------------------------------------------------------
# rewrite._split_title
# ---------------------------------------------------------------------------
def test_split_title_pulls_leading_h1():
    title, body = rew._split_title("# Fresh Title\n\nFirst paragraph.\n\nSecond.")
    assert title == "Fresh Title"
    assert body == "First paragraph.\n\nSecond."
    assert not body.startswith("#")


def test_split_title_without_h1_keeps_body():
    title, body = rew._split_title("No heading here.\n\nMore text.")
    assert title == ""
    assert body == "No heading here.\n\nMore text."


# ---------------------------------------------------------------------------
# publish builders
# ---------------------------------------------------------------------------
def test_build_doc_html_includes_backlink_and_article():
    html = pub.build_doc_html("T", "## Heading\n\nSome body text.", "https://site.com/post")
    assert "https://site.com/post" in html
    assert "Originally published at" in html
    assert "Some body text." in html
    # Backlink rendered as a real anchor.
    assert '<a href="https://site.com/post">' in html


def test_build_doc_html_no_source_omits_backlink():
    html = pub.build_doc_html("T", "Body.", "")
    assert "Originally published at" not in html
    assert "Body." in html


def test_build_sheet_rows_layout():
    rows = pub.build_sheet_rows("My Title", "# H1\n\nLine one.\n\nLine two.", "https://site.com/p")
    assert rows[0] == ["My Title"]
    assert rows[1] == ["Originally published at", "https://site.com/p"]
    # Each non-empty content line becomes its own row; blank lines are dropped.
    flat = [c for row in rows for c in row]
    assert "Line one." in flat
    assert "Line two." in flat
    assert all(any(cell.strip() for cell in row) or row == [""] for row in rows)


def test_build_sheet_rows_without_source():
    rows = pub.build_sheet_rows("T", "Body line.", "")
    assert rows[0] == ["T"]
    # No backlink row when there's no source URL.
    assert ["Originally published at", ""] not in rows
    assert ["Body line."] in rows
