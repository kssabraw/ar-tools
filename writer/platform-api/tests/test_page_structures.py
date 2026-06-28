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


def test_render_full_includes_replication_checklist():
    out = render_reference_structure(_complete_entry(), "service", mode="full")
    assert out is not None
    assert "Replication checklist:" in out
    # section_count from elements drives an explicit count directive
    assert "3 main" in out
    # element flags become a "include the same blocks" directive
    assert "FAQ" in out


def test_render_opening_mode_omits_outline():
    out = render_reference_structure(_complete_entry(), "blog_post", mode="opening")
    assert out is not None
    assert "REFERENCE OPENING" in out
    assert "Opening pattern: direct answer" in out
    # The opening block must NOT enumerate the full outline.
    assert "Outline:" not in out
    assert "Why it matters" not in out


def test_render_structure_mode_is_style_not_replica():
    out = render_reference_structure(_complete_entry(), "blog_post", mode="structure")
    assert out is not None
    assert "REFERENCE STRUCTURE STYLE" in out
    # Heading-depth + section-length texture directives are present.
    assert "Heading depth:" in out
    assert "Section length:" in out
    # It shows the outline for reference but must NOT force a section count/order
    # like full mode does (that would fight the SEO-driven outline).
    assert "Why it matters" in out
    assert "Replication checklist:" not in out
    assert "main (H2) sections in the same order" not in out


def test_render_structure_flags_short_sections():
    entry = {
        "status": "complete",
        "analysis": {
            "outline": [
                {"level": "H2", "heading": "Quick note", "approx_words": 20},
                {"level": "H3", "heading": "A sub-point", "approx_words": 30},
            ],
            "structure_summary": "Tight sections.",
            "elements": {},
        },
    }
    out = render_reference_structure(entry, "blog_post", mode="structure")
    assert out is not None
    # A <=45-word section is flagged as deliberate brevity to preserve.
    assert "1–2 sentences" in out
    # An H3 in the outline drives the "splits sections with H3" depth directive.
    assert "H3 sub-headings" in out or "H3 sub-point" in out


def test_page_types_constant():
    assert set(PAGE_TYPES) == {"local_landing", "service", "location", "blog_post", "product", "solution"}


# ── page_structure_eval (structural-fidelity scoring) ───────────────────────

def test_extract_outline_from_html():
    from services.page_structure_eval import extract_outline_from_html

    html = """
    <article>
      <h1>AC Repair in Austin</h1>
      <p>Direct answer paragraph.</p>
      <h2>Our Services</h2>
      <ul><li>Repair</li><li>Install</li></ul>
      <h2>Pricing</h2>
      <table><tr><td>Service</td><td>Cost</td></tr></table>
      <h2>Frequently Asked Questions</h2>
      <p>Q and A.</p>
    </article>
    """
    analysis = extract_outline_from_html(html)
    levels = [it["level"] for it in analysis["outline"]]
    assert levels == ["H1", "H2", "H2", "H2"]
    assert analysis["elements"]["section_count"] == 3
    assert analysis["elements"]["has_lists"] is True
    assert analysis["elements"]["has_table"] is True
    assert analysis["elements"]["has_faq"] is True


def test_extract_outline_from_markdown():
    from services.page_structure_eval import extract_outline_from_markdown

    md = (
        "# Title\n\nLead paragraph.\n\n"
        "## Section One\n\n- a\n- b\n\n"
        "## Section Two\n\n| h | h |\n| --- | --- |\n| x | y |\n\n"
        "## FAQ\n\nQuestions.\n"
    )
    analysis = extract_outline_from_markdown(md)
    assert analysis["elements"]["section_count"] == 3
    assert analysis["elements"]["has_lists"] is True
    assert analysis["elements"]["has_table"] is True
    assert analysis["elements"]["has_faq"] is True


def test_score_identical_structure_is_high():
    from services.page_structure_eval import extract_outline_from_html, score_structural_fidelity

    html = """
    <article>
      <h1>T</h1><p>p</p>
      <h2>One</h2><ul><li>x</li></ul>
      <h2>Two</h2><table><tr><td>a</td></tr></table>
      <h2>Frequently Asked Questions</h2><p>q</p>
    </article>
    """
    analysis = extract_outline_from_html(html)
    result = score_structural_fidelity(analysis, analysis)
    assert result["composite"] >= 95.0
    assert result["dimensions"]["section_count"] == 100.0


def test_score_divergent_structure_is_lower():
    from services.page_structure_eval import (
        extract_outline_from_html,
        extract_outline_from_markdown,
        score_structural_fidelity,
    )

    reference = extract_outline_from_html(
        "<article><h1>T</h1><p>p</p>"
        "<h2>One</h2><ul><li>x</li></ul>"
        "<h2>Two</h2><table><tr><td>a</td></tr></table>"
        "<h2>Frequently Asked Questions</h2><p>q</p></article>"
    )
    # Generated page: fewer sections, no list/table/FAQ.
    generated = extract_outline_from_markdown("# T\n\njust one paragraph and nothing else\n")
    result = score_structural_fidelity(reference, generated)
    assert result["composite"] < 60.0
    assert any("missing" in n for n in result["notes"])


def test_score_accepts_full_page_structures_entry():
    from services.page_structure_eval import extract_outline_from_html, score_structural_fidelity

    gen = extract_outline_from_html("<article><h1>T</h1><h2>A</h2><p>x</p></article>")
    # A full entry (with status/analysis wrapper) is unwrapped automatically.
    entry = {"status": "complete", "analysis": gen}
    result = score_structural_fidelity(entry, gen)
    assert result["composite"] >= 95.0
