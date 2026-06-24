"""Unit tests for the reference page-structure feature.

Covers the pure logic: chrome stripping, the prompt-block renderer, and the
create/update URL-diff that decides which pages to (re)scrape.
"""

from __future__ import annotations

from services.page_structure_render import render_reference_structure
from services.page_structure_scraper import PAGE_TYPES, strip_chrome


# ── strip_chrome ────────────────────────────────────────────────────────────

def test_strip_chrome_removes_nav_header_footer_and_popups():
    html = """
    <html><body>
      <header id="site-header">LOGO MENU</header>
      <nav class="navbar">Home About</nav>
      <div class="cookie-consent">Accept cookies?</div>
      <div class="newsletter-popup">Subscribe!</div>
      <main>
        <h1>AC Repair in Austin</h1>
        <p>Real content here.</p>
      </main>
      <aside class="sidebar">Related links</aside>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    cleaned = strip_chrome(html)
    assert "Real content here." in cleaned
    assert "AC Repair in Austin" in cleaned
    # Chrome is gone.
    for gone in ("LOGO MENU", "Home About", "Accept cookies?", "Subscribe!", "Related links", "Copyright 2026"):
        assert gone not in cleaned


def test_strip_chrome_prefers_main_landmark():
    html = "<body><div class='promo-bar'>SALE</div><main><p>Body</p></main></body>"
    cleaned = strip_chrome(html)
    assert "Body" in cleaned
    assert "SALE" not in cleaned


def test_strip_chrome_handles_empty():
    assert strip_chrome("") == "" or strip_chrome("") is not None


# ── render_reference_structure ──────────────────────────────────────────────

def _complete_entry():
    return {
        "url": "https://x.com/p",
        "status": "complete",
        "error": None,
        "analysis": {
            "outline": [
                {"level": "H1", "heading": "Title", "blocks": ["paragraph"], "approx_words": 50},
                {"level": "H2", "heading": "Why it matters", "blocks": ["paragraph", "list"], "approx_words": 200},
            ],
            "structure_summary": "Opens with a direct answer, then sections.",
            "elements": {"section_count": 3, "has_faq": True, "intro_pattern": "direct answer"},
        },
    }


def test_render_returns_none_when_not_complete():
    assert render_reference_structure({"status": "pending"}, "service") is None
    assert render_reference_structure({"status": "failed", "error": "x"}, "service") is None
    assert render_reference_structure(None, "service") is None
    assert render_reference_structure({}, "service") is None


def test_render_returns_none_when_analysis_empty():
    entry = {"status": "complete", "analysis": {"outline": [], "structure_summary": ""}}
    assert render_reference_structure(entry, "blog_post") is None


def test_render_produces_block_with_summary_outline_and_label():
    out = render_reference_structure(_complete_entry(), "service")
    assert out is not None
    assert "service" in out  # the page-type label
    assert "REFERENCE STRUCTURE" in out
    assert "Opens with a direct answer" in out
    assert "Why it matters" in out
    assert "Outline:" in out
    # element flags surfaced
    assert "FAQ" in out


# ── _sync_page_structures (create/update diff) ──────────────────────────────

def test_sync_page_structures():
    from models.clients import PageStructureUrls
    from routers.clients import _sync_page_structures

    # New client: one URL set -> pending entry + enqueue.
    urls = PageStructureUrls(service="https://x.com/s")
    merged, to_enqueue = _sync_page_structures({}, urls)
    assert merged["service"]["status"] == "pending"
    assert ("service", "https://x.com/s") in to_enqueue
    assert len(to_enqueue) == 1

    # Unchanged + already complete -> no re-enqueue, entry preserved.
    existing = {"service": {"url": "https://x.com/s", "status": "complete", "analysis": {"outline": []}}}
    merged2, enq2 = _sync_page_structures(existing, PageStructureUrls(service="https://x.com/s"))
    assert enq2 == []
    assert merged2["service"]["status"] == "complete"

    # Changed URL -> re-enqueue + reset to pending.
    merged3, enq3 = _sync_page_structures(existing, PageStructureUrls(service="https://x.com/new"))
    assert merged3["service"]["status"] == "pending"
    assert ("service", "https://x.com/new") in enq3

    # Cleared URL -> entry dropped.
    merged4, enq4 = _sync_page_structures(existing, PageStructureUrls(service=""))
    assert "service" not in merged4
    assert enq4 == []

    # None urls -> untouched.
    merged5, enq5 = _sync_page_structures(existing, None)
    assert merged5 == existing
    assert enq5 == []


def test_page_types_constant():
    assert set(PAGE_TYPES) == {"local_landing", "service", "location", "blog_post"}
