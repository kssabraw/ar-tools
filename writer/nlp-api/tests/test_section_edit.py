"""Unit tests for section-scoped page editing.

Pure + offline (bs4 only). Covers splitting a generated page into addressable
<section> blocks, splicing edits back by key, refusing unknown/blank edits (so a
hallucinated section id can't corrupt the page), preserving unedited sections
and their structure, keying by id / heading-slug / position, and the
no-<section> fallback contract that sends the caller to a whole-page rewrite.
Run with `pytest writer/nlp-api/tests/`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import section_edit as se  # noqa: E402


_PAGE = (
    "<article>"
    '<section id="intro"><h1>Roof Restoration Melbourne</h1>'
    "<p>We restore roofs across Melbourne.</p></section>"
    '<section id="services"><h2>Our Services</h2>'
    "<ul><li>Tile</li><li>Metal</li></ul>"
    "<table><thead><tr><th>Type</th></tr></thead><tbody><tr><td>Tile</td></tr></tbody></table>"
    "</section>"
    '<section id="faq"><h2>FAQ</h2><p>Q&amp;A here.</p></section>'
    "</article>"
)


# ── split_sections ───────────────────────────────────────────────────────────

def test_split_keys_from_ids_in_document_order():
    secs = se.split_sections(_PAGE)
    assert [s["key"] for s in secs] == ["intro", "services", "faq"]
    assert secs[0]["heading"] == "Roof Restoration Melbourne"
    assert secs[1]["heading"] == "Our Services"
    assert "<ul>" in secs[1]["inner"] and "<table>" in secs[1]["inner"]
    assert secs[1]["text"].startswith("Our Services")


def test_split_falls_back_to_heading_slug_then_position():
    html = (
        "<article>"
        "<section><h2>Why Choose Us</h2><p>a</p></section>"
        "<section><p>no heading</p></section>"
        "</article>"
    )
    keys = [s["key"] for s in se.split_sections(html)]
    assert keys[0] == "why-choose-us"
    assert keys[1] == "section-1"  # no id, no heading → position


def test_split_no_sections_returns_empty():
    # Caller uses [] to fall back to a whole-page rewrite.
    assert se.split_sections("<article><h2>x</h2><p>y</p></article>") == []
    assert se.split_sections("") == []
    assert se.split_sections(None) == []


def test_split_skips_nested_sections():
    html = '<article><section id="outer"><h2>Outer</h2><section id="inner"><p>x</p></section></section></article>'
    keys = [s["key"] for s in se.split_sections(html)]
    assert keys == ["outer"]  # only top-level


def test_split_disambiguates_duplicate_keys():
    html = (
        "<article>"
        '<section id="cta"><p>one</p></section>'
        '<section id="cta"><p>two</p></section>'
        "</article>"
    )
    keys = [s["key"] for s in se.split_sections(html)]
    assert keys[0] == "cta"
    assert keys[1] != "cta" and keys[1].startswith("cta")


# ── apply_section_edits ──────────────────────────────────────────────────────

def test_apply_edits_only_named_section():
    edits = {"services": "<h2>Our Services</h2><ul><li>Tile restoration</li><li>Repointing</li></ul>"}
    out, applied, skipped = se.apply_section_edits(_PAGE, edits)
    assert applied == ["services"] and skipped == []
    assert "Repointing" in out
    assert "<li>Metal</li>" not in out            # old services content replaced
    assert "We restore roofs across Melbourne" in out  # intro untouched
    assert "Q&amp;A here" in out or "Q&A here" in out   # faq untouched


def test_apply_edits_skips_unknown_key_never_appends():
    edits = {"nonexistent": "<p>injected junk</p>"}
    out, applied, skipped = se.apply_section_edits(_PAGE, edits)
    assert applied == [] and skipped == ["nonexistent"]
    assert "injected junk" not in out
    assert out == _PAGE  # nothing changed


def test_apply_edits_skips_blank_or_nonstring():
    edits = {"services": "   ", "faq": None, "intro": 123}
    out, applied, skipped = se.apply_section_edits(_PAGE, edits)
    assert applied == []
    assert set(skipped) == {"services", "faq", "intro"}
    assert out == _PAGE


def test_apply_edits_preserves_structure_of_replacement():
    # A replacement that keeps a table stays a table after splice.
    edits = {"services": "<h2>Our Services</h2><table><thead><tr><th>Service</th></tr></thead>"
                         "<tbody><tr><td>Tile restoration</td></tr></tbody></table>"}
    out, applied, _ = se.apply_section_edits(_PAGE, edits)
    assert applied == ["services"]
    assert out.count("<table>") == 1
    assert "Tile restoration" in out


def test_apply_edits_multiple_sections():
    edits = {
        "intro": "<h1>Roof Restoration Melbourne</h1><p>Trusted Melbourne roofing experts.</p>",
        "faq": "<h2>FAQ</h2><p>Yes, we offer free quotes.</p>",
    }
    out, applied, skipped = se.apply_section_edits(_PAGE, edits)
    assert set(applied) == {"intro", "faq"} and skipped == []
    assert "Trusted Melbourne roofing experts" in out
    assert "free quotes" in out
    assert "Our Services" in out  # untouched middle section


def test_apply_edits_empty_edits_is_noop():
    out, applied, skipped = se.apply_section_edits(_PAGE, {})
    assert out == _PAGE and applied == [] and skipped == []


# ── section_digest ───────────────────────────────────────────────────────────

def test_digest_lists_keys_headings_and_inner_html():
    digest = se.section_digest(se.split_sections(_PAGE))
    assert "[intro]" in digest and "[services]" in digest and "[faq]" in digest
    assert "Our Services" in digest
    assert "<ul>" in digest  # inner HTML included so the model preserves structure


def test_digest_caps_long_inner_html():
    big = "<article><section id='x'><h2>X</h2><p>" + ("word " * 5000) + "</p></section></article>"
    digest = se.section_digest(se.split_sections(big), max_inner_chars=500)
    assert "[truncated]" in digest
    assert len(digest) < 2000
