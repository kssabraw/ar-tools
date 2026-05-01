"""Tests for parsers.parse_serp meta_descriptions extraction (Brief v2.0).

Only covers the v2.0 additions — the heading / PAA / signal extraction
paths are exercised by upstream integration tests.
"""

from __future__ import annotations

from modules.brief.parsers import parse_serp


def _organic(position: int, title: str, description: str = "", url: str = "https://example.com") -> dict:
    return {
        "type": "organic",
        "rank_absolute": position,
        "rank_group": position,
        "url": url,
        "title": title,
        "description": description,
    }


def test_parse_serp_returns_meta_descriptions_in_position_order():
    items = [
        _organic(1, "TikTok Shop Explained", "Learn what TikTok Shop is and how it works for sellers."),
        _organic(2, "TikTok Shop Guide", "A practical guide to TikTok Shop covering setup."),
        _organic(3, "TikTok Shop FAQ", "Common questions about TikTok Shop answered."),
    ]
    _, _, _, titles, metas = parse_serp(items)
    assert len(metas) == 3
    assert metas[0].startswith("Learn what TikTok Shop")
    assert metas[1].startswith("A practical guide")
    assert metas[2].startswith("Common questions")
    assert len(titles) == 3


def test_parse_serp_skips_empty_descriptions():
    items = [
        _organic(1, "TikTok Shop A", "Real description here."),
        _organic(2, "TikTok Shop B", ""),
        _organic(3, "TikTok Shop C", "   "),  # whitespace-only
        _organic(4, "TikTok Shop D", "Another real one."),
    ]
    _, _, _, _, metas = parse_serp(items)
    assert len(metas) == 2
    assert metas == ["Real description here.", "Another real one."]


def test_parse_serp_strips_whitespace_around_descriptions():
    items = [
        _organic(1, "TikTok Shop", "   leading and trailing   "),
    ]
    _, _, _, _, metas = parse_serp(items)
    assert metas == ["leading and trailing"]


def test_parse_serp_ignores_descriptions_on_non_organic_items():
    items = [
        {"type": "people_also_ask", "items": [{"title": "What is TikTok Shop?"}]},
        {"type": "featured_snippet", "description": "Some snippet text"},
        _organic(1, "TikTok Shop", "real organic description"),
    ]
    _, signals, paa, _, metas = parse_serp(items)
    # Only organic descriptions feed the meta_descriptions list
    assert metas == ["real organic description"]
    assert signals.featured_snippet is True
    assert paa == ["What is TikTok Shop?"]


def test_parse_serp_returns_five_tuple_signature():
    """v2.0 schema change — parse_serp now returns 5 elements."""
    result = parse_serp([])
    assert len(result) == 5
    headings, signals, paa, titles, metas = result
    assert headings == []
    assert paa == []
    assert titles == []
    assert metas == []
