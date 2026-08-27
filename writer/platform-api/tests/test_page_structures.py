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


def test_strip_chrome_falls_back_when_aggressive_strip_nukes_content():
    # A WordPress/builder-style page: the only content is inside a div whose
    # class ('hero-banner') substring-matches a chrome hint ('banner'), and
    # there's no <main>/<article> landmark. The aggressive pass decomposes it
    # → empty → the gentle fallback must recover the content while still
    # dropping the hard-chrome <nav>/<footer>.
    html = """
    <html><body>
      <nav class="navbar">Home About</nav>
      <div class="hero-banner">
        <h1>Roof Restoration Sydney</h1>
        <p>We restore tile and metal roofs across Sydney.</p>
      </div>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    cleaned = strip_chrome(html)
    assert "Roof Restoration Sydney" in cleaned
    assert "We restore tile and metal roofs across Sydney." in cleaned
    # Hard chrome is still gone even in the fallback.
    assert "Home About" not in cleaned
    assert "Copyright 2026" not in cleaned


def test_strip_chrome_falls_back_when_aggressive_strip_loses_headings():
    # WordPress pattern: the heading sits in a div whose class substring-matches
    # 'header' (entry-header / section-header), so the aggressive hint pass
    # decomposes it — but OTHER text survives, so the old "only fall back when
    # empty" rule kept a heading-less result (→ 0 sections). The heading-aware
    # fallback must recover the heading.
    html = """
    <html><body>
      <div class="section-header"><h2>Our Services</h2></div>
      <div class="content-body"><p>We offer full roof restoration and repair across the region with a fast response.</p></div>
    </body></html>
    """
    cleaned = strip_chrome(html)
    assert "Our Services" in cleaned                      # the heading survived
    assert "roof restoration and repair" in cleaned
    from bs4 import BeautifulSoup
    assert BeautifulSoup(cleaned, "html.parser").find("h2") is not None


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


def test_extract_outline_from_html_ignores_stray_article_and_uses_content():
    """Regression: on an Elementor/WordPress page the pasted content sits in a
    <div data-elementor-type="single-post"> (NO <article>), while the Related
    Posts widget emits stray <article> cards. Blindly taking the first <article>
    scoped the outline to a related-post card and dropped every real heading (a
    reference scrape returned 0 sections despite dozens of headings in the HTML).
    The extractor must skip the low-heading <article> and segment the content."""
    from services.page_structure_eval import extract_outline_from_html

    html = """
    <main class="site-main">
      <div data-elementor-type="single-post" class="elementor">
        <div class="elementor-widget-container">
          <h1>What Is a Transportation Management System</h1>
          <h2>Why You Need a TMS</h2>
          <p>A TMS streamlines freight operations across carriers and modes.</p>
          <h2>Core Capabilities</h2>
          <p>Rating, routing, tendering, and settlement in one platform.</p>
          <h3>Freight Audit</h3>
          <p>Automated invoice validation catches billing errors.</p>
        </div>
      </div>
      <section class="elementor-widget-posts">
        <article class="elementor-post"><h3><a href="#">Related: 3PL basics</a></h3></article>
        <article class="elementor-post"><h3><a href="#">Related: LTL vs FTL</a></h3></article>
      </section>
    </main>
    """
    analysis = extract_outline_from_html(html)
    headings = [it["heading"] for it in analysis["outline"]]
    # The real content headings are captured (not scoped away to a related card).
    assert "What Is a Transportation Management System" in headings
    assert "Why You Need a TMS" in headings
    assert "Core Capabilities" in headings
    assert "Freight Audit" in headings
    assert analysis["elements"]["section_count"] >= 2  # the two content H2s


def test_extract_outline_prefers_article_when_it_holds_the_content():
    """The flip side: when a semantic <article>/<main> genuinely holds (nearly)
    all the headings, it is still used as the tight root — the generators emit
    flat <article> HTML and normal posts wrap content in <article>."""
    from services.page_structure_eval import extract_outline_from_html

    html = """
    <body>
      <main>
        <article>
          <h1>Post Title</h1>
          <h2>Section A</h2><p>body</p>
          <h2>Section B</h2><p>body</p>
        </article>
      </main>
    </body>
    """
    analysis = extract_outline_from_html(html)
    assert [it["heading"] for it in analysis["outline"]] == ["Post Title", "Section A", "Section B"]
    assert analysis["elements"]["section_count"] == 2


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


# ── deterministic detail: exact word counts + per-block composition ──────────

def test_extract_detailed_blocks_and_word_counts():
    from services.page_structure_eval import extract_outline_from_html

    html = """
    <article>
      <div class="hero"><h1>Roof Restoration in Denver</h1>
        <div><p>We restore tile and metal roofs fast.</p></div></div>
      <section><h2>Our Services</h2>
        <div class="wrap"><ul><li>Repair</li><li>Replace</li><li>Coat</li></ul></div></section>
      <h2>Contact Us</h2>
      <p>Call us today for a free quote.</p>
    </article>
    """
    analysis = extract_outline_from_html(html)
    outline = analysis["outline"]
    # Document-order segmentation works despite the div nesting.
    assert [it["level"] for it in outline] == ["H1", "H2", "H2"]

    # Word counts are exact (deterministic), not estimates.
    hero = outline[0]
    assert hero["word_count"] == 7  # "We restore tile and metal roofs fast."
    para_blocks = [b for b in hero["blocks"] if b["type"] == "paragraph"]
    assert para_blocks and para_blocks[0]["count"] == 1 and para_blocks[0]["words"] == 7

    # A list block carries its item count.
    services = outline[1]
    list_blocks = [b for b in services["blocks"] if b["type"] == "list"]
    assert list_blocks and list_blocks[0]["items"] == 3

    # A short CTA-flavored paragraph classifies as a cta block, not prose.
    contact = outline[2]
    assert any(b["type"] == "cta" for b in contact["blocks"])


# ── structural-fidelity gate: corrections builder + usable_analysis ──────────

def _ref_analysis():
    """A reference outline with 3 H2 sections, a list, a table and an FAQ."""
    from services.page_structure_eval import extract_outline_from_html

    return extract_outline_from_html(
        "<article><h1>Roof Restoration in Denver</h1><p>Direct answer.</p>"
        "<h2>Our Services</h2><ul><li>Repair</li><li>Replace</li></ul>"
        "<h2>Pricing</h2><table><tr><td>Service</td><td>Cost</td></tr></table>"
        "<h2>Frequently Asked Questions</h2><p>A question and its answer.</p></article>"
    )


def test_build_structure_corrections_flags_drift():
    from services.page_structure_eval import build_structure_corrections, extract_outline_from_html

    reference = _ref_analysis()
    # Drifted output: only 1 H2 section, no list/table/FAQ.
    generated = extract_outline_from_html(
        "<article><h1>Roofing</h1><h2>About Our Roofing</h2><p>just one long paragraph of prose</p></article>"
    )
    corrections = build_structure_corrections(reference, generated)
    assert corrections  # non-empty → the gate will retry
    # Section-count miss is named with the exact target + what was produced.
    assert "exactly 3 main H2 sections" in corrections
    assert "you produced 1" in corrections
    # Dropped structural blocks are called out.
    assert "an FAQ section" in corrections
    assert "a bulleted/numbered list" in corrections
    assert "a comparison/data table" in corrections


def test_build_structure_corrections_empty_when_matched():
    from services.page_structure_eval import build_structure_corrections

    reference = _ref_analysis()
    # Scoring a page against itself: no layout drift → no corrections.
    assert build_structure_corrections(reference, reference) == ""


def test_build_structure_corrections_consolidate_when_too_many_sections():
    from services.page_structure_eval import build_structure_corrections, extract_outline_from_html

    reference = _ref_analysis()  # 3 sections
    generated = extract_outline_from_html(
        "<article><h1>T</h1><h2>A</h2><p>x</p><h2>B</h2><p>y</p>"
        "<h2>C</h2><p>z</p><h2>D</h2><p>w</p><h2>E</h2><p>v</p></article>"  # 5 sections
    )
    corrections = build_structure_corrections(reference, generated)
    assert "exactly 3 main H2 sections" in corrections
    assert "Consolidate sections" in corrections


def test_structure_deficiency_shapes_a_reopt_deficiency():
    from services.page_structure_eval import extract_outline_from_html, structure_deficiency

    reference = _ref_analysis()  # 3 sections + list/table/FAQ
    drift = extract_outline_from_html(
        "<article><h1>Roofing</h1><h2>About Our Roofing</h2><p>just prose</p></article>"
    )
    d = structure_deficiency(reference, drift, label="service", min_composite=85.0)
    assert d is not None
    # Shaped like a scorer deficiency so the service_writer reopt directive renders it.
    assert d["engine"].startswith("Page structure fidelity")
    assert "service" in d["issues"][0]
    assert isinstance(d["recommendations"], list) and d["recommendations"]
    # Recommendations are the corrections, de-bulleted.
    assert any("exactly 3 main H2 sections" in r for r in d["recommendations"])
    assert not any(r.startswith("- ") for r in d["recommendations"])


def test_structure_deficiency_none_when_matched_or_no_reference():
    from services.page_structure_eval import structure_deficiency

    reference = _ref_analysis()
    # Matched layout → no deficiency.
    assert structure_deficiency(reference, reference, label="service", min_composite=85.0) is None
    # Empty reference outline → no deficiency (nothing to enforce).
    empty = {"outline": [], "elements": {}}
    assert structure_deficiency(empty, reference, label="service", min_composite=85.0) is None


def test_usable_analysis_accessor():
    from services.page_structure_render import usable_analysis

    complete = _complete_entry()
    analysis = usable_analysis(complete)
    assert analysis is not None
    assert analysis is complete["analysis"]
    # Non-usable entries return None (mirrors the renderer's gate).
    assert usable_analysis({"status": "pending"}) is None
    assert usable_analysis(None) is None
    assert usable_analysis({"status": "complete", "analysis": {"outline": [], "structure_summary": ""}}) is None


def test_extract_does_not_double_count_nested_content():
    from services.page_structure_eval import extract_outline_from_html

    # A <p> inside an <li> must count once (via the list), not twice.
    html = "<article><h2>Items</h2><ul><li><p>alpha beta</p></li><li>gamma</li></ul></article>"
    outline = extract_outline_from_html(html)["outline"]
    section = outline[0]
    assert section["word_count"] == 3  # alpha beta gamma
    assert [b["type"] for b in section["blocks"]] == ["list"]
    assert section["blocks"][0]["items"] == 2


def test_word_fit_dimension_in_scoring():
    from services.page_structure_eval import extract_outline_from_html, score_structural_fidelity

    long_html = (
        "<article><h1>T</h1><p>" + "word " * 100 + "</p>"
        "<h2>A</h2><p>" + "word " * 100 + "</p></article>"
    )
    reference = extract_outline_from_html(long_html)

    # Identical -> perfect word fit.
    same = score_structural_fidelity(reference, reference)
    assert same["dimensions"]["word_fit"] == 100.0
    assert any(n.startswith("words:") for n in same["notes"])

    # Same layout but each section a fraction of the size -> word fit drops.
    short_html = (
        "<article><h1>T</h1><p>" + "word " * 10 + "</p>"
        "<h2>A</h2><p>" + "word " * 10 + "</p></article>"
    )
    generated = extract_outline_from_html(short_html)
    diverged = score_structural_fidelity(reference, generated)
    assert diverged["dimensions"]["word_fit"] < 40.0
    # Section count + heading order still perfect -> word-fit is what separates them.
    assert diverged["dimensions"]["section_count"] == 100.0


# ── scraper: deterministic + LLM-annotation merge ───────────────────────────

def test_merge_annotations_keeps_deterministic_fields():
    from services.page_structure_scraper import _merge_annotations

    outline = [
        {"level": "H2", "heading": "Our Amazing Roof Repair in Denver",
         "word_count": 120, "blocks": [{"type": "paragraph", "count": 2, "words": 120}]},
        {"level": "H2", "heading": "Testimonials", "word_count": 60, "blocks": []},
    ]
    annotations = {
        "sections": [
            {"index": 0, "generalized_heading": "Service overview",
             "intent": "service_detail", "intent_note": "describes the offering"},
            {"index": 1, "generalized_heading": "Reviews", "intent": "BOGUS", "intent_note": ""},
        ],
    }
    merged = _merge_annotations(outline, annotations)

    # Deterministic fields are untouched.
    assert merged[0]["word_count"] == 120
    assert merged[0]["blocks"] == [{"type": "paragraph", "count": 2, "words": 120}]
    # LLM semantics overlaid.
    assert merged[0]["heading"] == "Service overview"
    assert merged[0]["intent"] == "service_detail"
    assert merged[0]["intent_note"] == "describes the offering"
    # An out-of-vocabulary intent falls back to "other".
    assert merged[1]["intent"] == "other"


def test_merge_annotations_missing_section_keeps_real_heading():
    from services.page_structure_scraper import _merge_annotations

    outline = [{"level": "H2", "heading": "Real Heading", "word_count": 30, "blocks": []}]
    merged = _merge_annotations(outline, {"sections": []})
    assert merged[0]["heading"] == "Real Heading"
    assert "intent" not in merged[0]


def test_intent_tags_include_expected_vocab():
    from services.page_structure_scraper import INTENT_TAGS

    assert {"hero", "trust", "cta", "faq", "pricing", "other"} <= set(INTENT_TAGS)


# ── render: intent + hard targets (new schema) + back-compat ────────────────

def _rich_entry():
    return {
        "status": "complete",
        "analysis": {
            "outline": [
                {"level": "H1", "heading": "Service overview", "intent": "hero",
                 "intent_note": "opening pitch", "word_count": 60,
                 "blocks": [{"type": "paragraph", "count": 1, "words": 60}]},
                {"level": "H2", "heading": "What we do", "intent": "service_detail",
                 "word_count": 180,
                 "blocks": [{"type": "paragraph", "count": 2, "words": 140},
                            {"type": "list", "count": 1, "words": 40, "items": 5}]},
            ],
            "structure_summary": "Hero, then service detail with a list.",
            "elements": {"section_count": 2, "approx_total_words": 240,
                         "has_lists": True, "intro_pattern": "hero + value prop"},
        },
    }


def test_render_full_emits_intent_and_hard_targets():
    out = render_reference_structure(_rich_entry(), "service", mode="full")
    assert out is not None
    # Section intent surfaced with a human label.
    assert "hero / value prop" in out
    assert "service detail" in out
    # Per-section targets: word count + block composition with item count.
    assert "~180 words" in out
    assert "5 items" in out
    # Hard-target directives in the checklist.
    assert "within about 15%" in out
    assert "block composition" in out
    assert "240 total words" in out


def test_render_structure_mode_uses_exact_word_count():
    # New-shape entry with a deliberately tiny section -> brevity is preserved.
    entry = {
        "status": "complete",
        "analysis": {
            "outline": [
                {"level": "H2", "heading": "Quick note", "word_count": 20, "blocks": []},
                {"level": "H3", "heading": "Detail", "word_count": 30, "blocks": []},
            ],
            "structure_summary": "Tight.",
            "elements": {},
        },
    }
    out = render_reference_structure(entry, "blog_post", mode="structure")
    assert out is not None
    assert "1–2 sentences" in out  # word_count (not approx_words) drives brevity


def test_render_back_compat_with_legacy_analysis():
    # A pre-upgrade analysis (approx_words + string blocks, no intent) still renders
    # in every mode without error.
    legacy = _complete_entry()
    for mode in ("full", "opening", "structure"):
        out = render_reference_structure(legacy, "service", mode=mode)
        assert out is not None
        assert "Why it matters" in out or mode == "opening"


# ── llm_annotate_structure result validation ────────────────────────────────
# Valid JSON is not necessarily a JSON *object*. A bare `null` parses fine and
# then crashes every caller with "'NoneType' object has no attribute 'get'" —
# 6 page_structure_scrape jobs died exactly that way.
import asyncio  # noqa: E402

import pytest  # noqa: E402

from services import page_structure_scraper as pss  # noqa: E402
from services import report_llm  # noqa: E402


_EMPTY = {"sections": [], "structure_summary": "", "intro_pattern": ""}


@pytest.mark.parametrize("payload", ["null", "[1, 2]", '"a string"', "42"])
def test_llm_annotate_degrades_when_json_is_not_an_object(monkeypatch, payload):
    async def _fake_generate_text(**_kwargs):
        return payload

    monkeypatch.setattr(report_llm, "generate_text", _fake_generate_text)

    result = asyncio.run(pss.llm_annotate_structure("<p>hi</p>", [{"heading": "H"}], "blog_post"))

    assert result == _EMPTY
    # The contract callers rely on: always a dict, so .get() is always safe.
    assert result.get("intro_pattern") == ""


def test_llm_annotate_passes_through_a_real_object(monkeypatch):
    async def _fake_generate_text(**_kwargs):
        return '{"sections": [{"i": 0}], "structure_summary": "s", "intro_pattern": "p"}'

    monkeypatch.setattr(report_llm, "generate_text", _fake_generate_text)

    result = asyncio.run(pss.llm_annotate_structure("<p>hi</p>", [{"heading": "H"}], "blog_post"))

    assert result["structure_summary"] == "s"
    assert result["intro_pattern"] == "p"


# ── manual (pasted / uploaded) page structures ──────────────────────────────
# The no-website capture path: a written spec parsed into the SAME analysis
# shape a scrape produces. The load-bearing rule is that a number the client
# never stated must never appear as a target — see page_structure_manual.

def test_normalize_sections_keeps_only_stated_numbers():
    from services.page_structure_manual import normalize_sections

    out = normalize_sections([
        {"heading": "Hero", "level": "h2", "intent": "hero", "intent_note": "Lead in",
         "word_count": 90, "blocks": [{"type": "cta", "count": 1}]},
        # No word_count / blocks stated -> neither may be invented.
        {"heading": "Why choose us", "level": "H3", "intent": "value_prop"},
    ])

    assert [s["heading"] for s in out] == ["Hero", "Why choose us"]
    assert out[0]["level"] == "H2"  # lowercase normalized
    assert out[0]["word_count"] == 90
    assert out[0]["blocks"] == [{"type": "cta", "count": 1}]
    assert out[1]["level"] == "H3"
    assert "word_count" not in out[1]
    assert "blocks" not in out[1]


def test_normalize_sections_rejects_bad_values():
    from services.page_structure_manual import normalize_sections

    out = normalize_sections([
        {"heading": "  ", "intent": "hero"},                      # no heading -> dropped
        {"heading": "Ok", "level": "H7", "intent": "not_a_tag",   # bad level/intent
         "word_count": 0,                                         # non-positive -> dropped
         "blocks": [{"type": "bullet list"}, {"type": "list", "items": 5}]},
        "not-a-dict",
    ])

    assert len(out) == 1
    assert out[0]["level"] == "H2"
    assert out[0]["intent"] == "other"
    assert "word_count" not in out[0]
    # An unknown block type is dropped rather than passed through: block scoring
    # is a set intersection of type names, so a synonym reads as a missing block.
    assert out[0]["blocks"] == [{"type": "list", "count": 1, "items": 5}]


def test_normalize_sections_handles_non_list():
    from services.page_structure_manual import normalize_sections

    assert normalize_sections(None) == []
    assert normalize_sections({"sections": []}) == []


def test_build_analysis_derives_elements_deterministically():
    from services.page_structure_manual import build_analysis

    analysis = build_analysis(
        {
            "sections": [
                {"heading": "Hero", "level": "H2", "intent": "hero", "word_count": 100},
                {"heading": "Services", "level": "H2", "intent": "service_detail",
                 "word_count": 200, "blocks": [{"type": "list", "items": 4}]},
                {"heading": "Common questions", "level": "H2", "intent": "faq", "word_count": 120},
            ],
            "structure_summary": "Opens with a hero, then services, then FAQ.",
            "intro_pattern": "hero statement + value prop",
        },
        "Hero section. Services list. FAQ block.",
    )

    el = analysis["elements"]
    assert el["section_count"] == 3
    # Every section is sized here, so the total is meaningful. When only SOME are
    # sized it must be dropped instead — see the partial-counts test below.
    assert el["approx_total_words"] == 420
    assert el["has_lists"] is True
    # A declared `faq` intent counts even without a tagged block.
    assert el["has_faq"] is True
    assert el["intro_pattern"] == "hero statement + value prop"
    assert analysis["structure_summary"].startswith("Opens with a hero")


def test_build_analysis_tolerates_garbage():
    from services.page_structure_manual import build_analysis

    analysis = build_analysis("not a dict", "")
    assert analysis["outline"] == []
    assert analysis["structure_summary"] == ""


def test_parse_guidelines_raises_when_no_sections_found(monkeypatch):
    """An empty parse must FAIL rather than store a complete-but-useless entry:
    unlike the scraper's annotation pass, the LLM is the whole extraction here."""
    from services import page_structure_manual as psm

    async def _fake_generate_text(**_kwargs):
        return '{"sections": [], "structure_summary": "No structure described."}'

    monkeypatch.setattr(report_llm, "generate_text", _fake_generate_text)

    with pytest.raises(ValueError):
        asyncio.run(psm.parse_guidelines("some prose that isn't a page spec", "service"))


def test_parse_guidelines_raises_on_unparseable_response(monkeypatch):
    from services import page_structure_manual as psm

    async def _fake_generate_text(**_kwargs):
        return "I'm afraid I can't do that."

    monkeypatch.setattr(report_llm, "generate_text", _fake_generate_text)

    with pytest.raises(ValueError):
        asyncio.run(psm.parse_guidelines("Hero — 80 words", "service"))


def test_parse_guidelines_requires_text():
    from services import page_structure_manual as psm

    with pytest.raises(ValueError):
        asyncio.run(psm.parse_guidelines("   ", "service"))


def test_parse_guidelines_happy_path_strips_fences(monkeypatch):
    from services import page_structure_manual as psm

    async def _fake_generate_text(**_kwargs):
        return (
            '```json\n'
            '{"sections": [{"heading": "Hero", "level": "H2", "intent": "hero", '
            '"word_count": 80}], "structure_summary": "Hero then detail.", '
            '"intro_pattern": "hero statement"}\n'
            '```'
        )

    monkeypatch.setattr(report_llm, "generate_text", _fake_generate_text)

    analysis = asyncio.run(psm.parse_guidelines("Hero — 80 words", "service"))
    assert analysis["outline"][0]["heading"] == "Hero"
    assert analysis["elements"]["intro_pattern"] == "hero statement"


# ── manual entries flow through the existing consumers unchanged ────────────

def _manual_entry(with_counts: bool) -> dict:
    section = {"heading": "Hero", "level": "H2", "intent": "hero", "intent_note": "Lead in"}
    second = {"heading": "Objections", "level": "H2", "intent": "objection"}
    if with_counts:
        section["word_count"] = 80
        second["word_count"] = 150
    return {
        "url": "",
        "source": "manual",
        "guidelines_text": "Hero, then objections.",
        "status": "complete",
        "analysis": {
            "outline": [section, second],
            "structure_summary": "Hero then objection handling.",
            "elements": {"section_count": 2, "has_cta": True},
        },
    }


def test_render_full_omits_word_targets_when_guidelines_state_none():
    """A spec that names sections but no lengths must not produce a word-count
    directive — the writer would be held to a number nobody specified."""
    out = render_reference_structure(_manual_entry(with_counts=False), "service", mode="full")
    assert out is not None
    # Section purposes still come through as hard layout directives.
    assert "objection handling" in out
    assert "Replication checklist:" in out
    assert "same number, order, and purpose" in out or "main (H2) sections" in out
    # ...but nothing about hitting word counts or reproducing block composition.
    assert "word count" not in out
    assert "block composition" not in out
    # And no dangling "— target" with nothing after it.
    assert "— target\n" not in out and not out.endswith("— target")


def test_render_full_keeps_word_targets_when_guidelines_state_them():
    out = render_reference_structure(_manual_entry(with_counts=True), "service", mode="full")
    assert out is not None
    assert "~80 words" in out
    assert "word count" in out


def test_manual_entry_is_usable_and_scores_without_word_counts():
    """The structural gate must not burn regeneration passes chasing word counts
    a manual reference never carried: word_fit is a free pass in that case."""
    from services.page_structure_eval import score_structural_fidelity
    from services.page_structure_render import usable_analysis

    entry = _manual_entry(with_counts=False)
    assert usable_analysis(entry) is not None

    generated = {
        "outline": [
            {"heading": "Hero", "level": "H2", "word_count": 120},
            {"heading": "Objections", "level": "H2", "word_count": 300},
        ],
        "elements": {"section_count": 2, "has_cta": True},
    }
    result = score_structural_fidelity(entry, generated)
    assert result["dimensions"]["word_fit"] == 100.0
    assert result["composite"] >= 85.0


def test_sync_page_structure_guidelines():
    from models.clients import PageStructureGuideline, PageStructureGuidelines
    from routers.clients import _sync_page_structure_guidelines

    # New spec -> pending entry + enqueue.
    guides = PageStructureGuidelines(
        service=PageStructureGuideline(text="Hero — 80 words", original_filename="spec.docx")
    )
    merged, enq = _sync_page_structure_guidelines({}, guides)
    assert merged["service"]["status"] == "pending"
    assert merged["service"]["source"] == "manual"
    assert enq == [("service", "Hero — 80 words", "spec.docx")]

    # Unchanged + complete -> no re-parse (an LLM call we'd pay for nothing).
    existing = {
        "service": {
            "source": "manual", "guidelines_text": "Hero — 80 words",
            "status": "complete", "analysis": {"outline": [{"heading": "Hero"}]},
        }
    }
    _, enq2 = _sync_page_structure_guidelines(
        existing, PageStructureGuidelines(service=PageStructureGuideline(text="Hero — 80 words"))
    )
    assert enq2 == []

    # Changed text -> re-parse.
    merged3, enq3 = _sync_page_structure_guidelines(
        existing, PageStructureGuidelines(service=PageStructureGuideline(text="Hero — 120 words"))
    )
    assert merged3["service"]["status"] == "pending"
    assert enq3 == [("service", "Hero — 120 words", None)]

    # Cleared -> manual entry dropped.
    merged4, _ = _sync_page_structure_guidelines(
        existing, PageStructureGuidelines(service=PageStructureGuideline(text=""))
    )
    assert "service" not in merged4

    # None -> untouched.
    merged5, enq5 = _sync_page_structure_guidelines(existing, None)
    assert merged5 == existing and enq5 == []


def test_guidelines_and_urls_do_not_clobber_each_other():
    """The client form submits every URL field on every save, so a blank URL must
    not delete a page type configured via guidelines (and vice versa)."""
    from models.clients import (
        PageStructureGuideline, PageStructureGuidelines, PageStructureUrls,
    )
    from routers.clients import _sync_page_structure_guidelines, _sync_page_structures

    existing = {
        "service": {"source": "manual", "guidelines_text": "Hero", "status": "complete",
                    "analysis": {"outline": [{"heading": "Hero"}]}},
        "blog_post": {"url": "https://x.com/b", "source": "scrape", "status": "complete",
                      "analysis": {"outline": [{"heading": "Intro"}]}},
    }

    # A save with all URL fields blank keeps the manual `service` entry.
    merged, _ = _sync_page_structures(existing, PageStructureUrls(blog_post="https://x.com/b"))
    assert "service" in merged

    # A save with all guideline fields blank keeps the scraped `blog_post` entry.
    merged2, _ = _sync_page_structure_guidelines(
        merged, PageStructureGuidelines(service=PageStructureGuideline(text="Hero"))
    )
    assert "blog_post" in merged2
    assert merged2["blog_post"]["url"] == "https://x.com/b"


def test_assert_single_structure_source_rejects_both():
    from fastapi import HTTPException

    from models.clients import (
        PageStructureGuideline, PageStructureGuidelines, PageStructureUrls,
    )
    from routers.clients import _assert_single_structure_source

    with pytest.raises(HTTPException) as exc:
        _assert_single_structure_source(
            PageStructureUrls(service="https://x.com/s"),
            PageStructureGuidelines(service=PageStructureGuideline(text="Hero — 80 words")),
        )
    assert exc.value.status_code == 422
    assert "service" in str(exc.value.detail)

    # Different page types is not a conflict.
    _assert_single_structure_source(
        PageStructureUrls(service="https://x.com/s"),
        PageStructureGuidelines(blog_post=PageStructureGuideline(text="Intro")),
    )


def test_build_analysis_drops_total_words_when_counts_are_partial():
    """A spec that sizes SOME sections must not produce a whole-page total: the
    partial sum renders as 'aim for roughly N total words' and would squeeze the
    page down to the size of only its documented sections."""
    from services.page_structure_manual import build_analysis

    partial = build_analysis(
        {"sections": [
            {"heading": "Hero", "level": "H2", "intent": "hero", "word_count": 100},
            {"heading": "Concerns", "level": "H2", "intent": "objection"},  # unsized
        ]},
        "",
    )
    assert partial["elements"]["approx_total_words"] == 0

    # Every section sized -> the total is real and is kept.
    full = build_analysis(
        {"sections": [
            {"heading": "Hero", "level": "H2", "intent": "hero", "word_count": 100},
            {"heading": "Concerns", "level": "H2", "intent": "objection", "word_count": 150},
        ]},
        "",
    )
    assert full["elements"]["approx_total_words"] == 250


def test_render_full_omits_total_words_directive_for_partial_counts():
    from services.page_structure_manual import build_analysis

    analysis = build_analysis(
        {"sections": [
            {"heading": "Hero", "level": "H2", "intent": "hero", "word_count": 100},
            {"heading": "Concerns", "level": "H2", "intent": "objection"},
        ]},
        "",
    )
    out = render_reference_structure({"status": "complete", "analysis": analysis}, "service")
    assert out is not None
    assert "total words across the page" not in out
    # The per-section targets that WERE stated still come through.
    assert "~100 words" in out


# ── scale_analysis_words (SERP-budget rescaling of the reference layout) ──────

from services.page_structure_render import (  # noqa: E402
    scale_analysis_words,
    outline_total_words,
)


def _scale_ref():
    """A reference analysis summing to 3177 words (FCR-shaped) — 3 sections."""
    return {
        "outline": [
            {"level": "H1", "heading": "Hero", "intent": "hero", "word_count": 600,
             "blocks": [{"type": "paragraph", "count": 2, "words": 600}]},
            {"level": "H2", "heading": "Services", "intent": "service_detail", "word_count": 1977,
             "blocks": [{"type": "paragraph", "count": 3, "words": 1500},
                        {"type": "list", "count": 1, "items": 6, "words": 477}]},
            {"level": "H2", "heading": "FAQ", "intent": "faq", "word_count": 600,
             "blocks": [{"type": "paragraph", "count": 4, "words": 600}]},
        ],
        "elements": {"section_count": 3, "approx_total_words": 3177,
                     "has_faq": True, "has_cta": True},
        "structure_summary": "hero, services, faq",
    }


def test_scale_down_to_serp_budget_preserves_proportions():
    a = _scale_ref()
    assert outline_total_words(a) == 3177
    scaled = scale_analysis_words(a, 1571)
    # total lands within rounding of the target
    assert abs(outline_total_words(scaled) - 1571) <= 3
    # proportions preserved: services stays the biggest section
    counts = [s["word_count"] for s in scaled["outline"]]
    assert counts[1] > counts[0] and counts[1] > counts[2]
    # block-level word counts scaled too; total set to the target
    assert scaled["outline"][1]["blocks"][0]["words"] < 1500
    assert scaled["elements"]["approx_total_words"] == 1571


def test_scale_never_mutates_input():
    a = _scale_ref()
    scale_analysis_words(a, 900)
    assert outline_total_words(a) == 3177  # original untouched
    assert a["elements"]["approx_total_words"] == 3177


def test_scale_can_scale_up_when_reference_is_short():
    # SERP budget, not the reference's own length, sets the target.
    short = {"outline": [{"level": "H2", "heading": "X", "word_count": 200}]}
    scaled = scale_analysis_words(short, 1000)
    assert scaled["outline"][0]["word_count"] == 1000


def test_scale_noop_without_target_or_outline_or_words():
    a = _scale_ref()
    assert scale_analysis_words(a, None) is a          # no target → unchanged object
    assert scale_analysis_words(a, 0) is a
    empty = {"outline": []}
    assert scale_analysis_words(empty, 1571) is empty   # nothing to scale
    no_words = {"outline": [{"level": "H2", "heading": "X"}]}
    assert scale_analysis_words(no_words, 1571) is no_words  # no measurable length


def test_render_uses_scaled_targets_not_reference_length():
    entry = {"status": "complete", "analysis": _scale_ref()}
    block = render_reference_structure(entry, "local_landing", target_words=1571)
    assert block is not None
    assert "3177" not in block          # the reference's own length never reaches the writer
    assert "1571" in block              # the SERP budget does
    # without a target it still renders the raw reference (back-compat)
    raw = render_reference_structure(entry, "local_landing")
    assert raw is not None and "3177" in raw
