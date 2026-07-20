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
