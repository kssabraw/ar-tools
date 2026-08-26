"""Unit tests for the deterministic blog/AEO structure analysis.

Pure + offline — no network, no Anthropic (bs4 only). Covers the structural_aeo
engine (R4 Key Takeaways / R6 paragraph cap / R7 citations / scannability /
heading structure) and the abbreviation-aware sentence counter.
Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blog_structure as bs  # noqa: E402


_GOOD = (
    "<h1>Roof Repair Guide</h1>"
    "<h2>Key Takeaways</h2><ul><li>Roof repair costs vary widely.</li>"
    "<li>Act fast on active leaks.</li></ul>"
    "<h2>What causes roof leaks?</h2><p>Leaks happen. Water gets in. Fix them fast.</p>"
    "<h2>How to fix a leak</h2><p>Call a pro. According to "
    '<a href="https://example.com">Example</a> most fixes are affordable.</p>'
    "<h3>DIY options</h3><p>" + ("word " * 320) + "</p>"
)


def test_count_sentences_basic():
    assert bs.count_sentences("One. Two. Three. Four. Five. Six.") == 6
    assert bs.count_sentences("") == 0
    assert bs.count_sentences("No terminal punctuation here") == 1


def test_count_sentences_ignores_abbreviations():
    # 'U.S.' and 'e.g.' must not count as sentence ends → 2 real sentences.
    assert bs.count_sentences("The U.S. rate is high, e.g. 5%. It then rose.") == 2


def test_metrics_wellformed_article():
    m = bs.structure_metrics(_GOOD)
    assert m["h2"] == 3
    assert m["has_key_takeaways"] is True
    assert m["lists"] == 1
    assert m["long_paragraphs"] == 0
    assert m["citations"] == 1
    assert m["words"] >= 300


def test_structural_score_wellformed_is_full():
    assert bs.compute_blog_structural_aeo(_GOOD)["score"] == 100


def test_structural_score_penalises_thin_article():
    bad = "<h1>Thing</h1><h2>Only section</h2><p>One. Two. Three. Four. Five. Six.</p>"
    res = bs.compute_blog_structural_aeo(bad)
    # no takeaways (-20) + <3 h2 (-15) + no list (-10) + long para (-5) +
    # no citation (-15) + <300 words (-15) = 20
    assert res["score"] == 20
    joined = " ".join(res["issues"]).lower()
    assert "key takeaway" in joined
    assert "cap" in joined  # paragraph-length violation named


def test_citation_markers_count_when_links_absent():
    # A suite-reconstructed article may still carry {{cit_N}} markers.
    html = "<h2>Key Takeaways</h2><ul><li>x</li></ul><p>A stat. {{cit_1}}</p>"
    assert bs.structure_metrics(html)["citations"] >= 1


def test_detect_blog_structure_renders_facts():
    facts = bs.detect_blog_structure(_GOOD)
    assert "HTML STRUCTURE FACTS" in facts
    assert "Key Takeaways" in facts
    assert "H2 sections" in facts
