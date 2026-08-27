"""Unit tests for the deterministic SERP-signal coverage engine's UI payload.

Covers the additive fields surfaced to the generated-page view: entities_used /
entities_missing (page-level) and the per-zone found/target breakdown. Pure +
offline (bs4 only) — no network, no Anthropic.
Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _serp_analysis():
    """A minimal SERP analysis with keyword + entity zone targets and quadgrams."""
    return {
        "related_keywords": {
            "h2_h3": [{"term": "roof restoration"}, {"term": "roof repairs"}],
            "paragraphs": [{"term": "tile roof"}, {"term": "gutters"}],
        },
        "zone_targets": {
            "h2_h3": {"target": 2, "entity_target": 1},
            "paragraphs": {"target": 2, "entity_target": 2},
        },
        "google_entities": [
            {"name": "Melbourne", "page_spread": 5, "recommended_mentions": 4},
            {"name": "Colorbond", "page_spread": 4, "recommended_mentions": 3},
            {"name": "Slate", "page_spread": 3, "recommended_mentions": 2},
        ],
        "top_quadgrams": [{"phrase": "licensed roofing contractor"}],
    }


def test_reports_entities_used_and_missing():
    html = (
        "<article><h2>Roof Restoration in Melbourne</h2>"
        "<p>We install Colorbond roofing across the city. Tile roof work too.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    # Melbourne + Colorbond appear; Slate does not.
    assert set(res["entities_used"]) == {"Melbourne", "Colorbond"}
    assert res["entities_missing"] == ["Slate"]


def test_reports_per_zone_found_and_target():
    html = (
        "<article><h2>Roof Restoration and Roof Repairs</h2>"
        "<p>Tile roof care in Melbourne.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    zones = {z["zone"]: z for z in res["zones"]}
    # Both H2/H3 keyword targets are met.
    assert zones["H2/H3 headings"]["keyword_found"] == 2
    assert zones["H2/H3 headings"]["keyword_target"] == 2
    # Paragraph zone carries both keyword and entity found/target.
    assert zones["paragraphs"]["keyword_target"] == 2
    assert zones["paragraphs"]["entity_target"] == 2


def test_no_serp_analysis_has_no_coverage_fields():
    res = main._compute_serp_signal_coverage("<p>hi</p>", None)
    assert res["score"] == 50
    assert "entities_used" not in res  # degraded payload stays minimal


def test_entity_detail_reports_current_recommended_and_shortfall():
    # Melbourne x2, Colorbond x1, Slate x0 on the page.
    html = (
        "<article><h2>Roof Restoration in Melbourne</h2>"
        "<p>Colorbond roofing across Melbourne. We install it well.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    detail = {d["name"]: d for d in res["entity_detail"]}
    # current mention counts (word-boundary, page-level)
    assert detail["Melbourne"]["current"] == 2
    assert detail["Colorbond"]["current"] == 1
    assert detail["Slate"]["current"] == 0
    # recommended carried from the SERP analysis
    assert detail["Melbourne"]["recommended"] == 4
    assert detail["Slate"]["recommended"] == 2
    # shortfall = max(0, recommended - current)
    assert detail["Melbourne"]["shortfall"] == 2   # 4 - 2
    assert detail["Colorbond"]["shortfall"] == 2   # 3 - 1
    assert detail["Slate"]["shortfall"] == 2       # 2 - 0
    # biggest gaps first, ties broken by page_spread (Melbourne before others)
    assert res["entity_detail"][0]["name"] == "Melbourne"
    # rollups
    assert set(res["entities_under_target"]) == {"Melbourne", "Colorbond", "Slate"}
    assert res["total_entity_shortfall"] == 6


def test_word_boundary_counting_does_not_match_substrings():
    # "Slate" must not be counted inside "Slater"; "tile" not inside "tiles".
    html = "<article><p>Mr Slater fitted the tiles. Slate is different.</p></article>"
    serp = {
        "google_entities": [
            {"name": "Slate", "page_spread": 3, "recommended_mentions": 2},
            {"name": "tile", "page_spread": 2, "recommended_mentions": 2},
        ],
    }
    res = main._compute_serp_signal_coverage(html, serp)
    detail = {d["name"]: d for d in res["entity_detail"]}
    assert detail["Slate"]["current"] == 1   # only the standalone "Slate"
    assert detail["tile"]["current"] == 0    # "tiles" does not count
