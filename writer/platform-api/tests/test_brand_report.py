"""Unit tests for services.brand_report pure helpers (build_snapshot / render)."""

from __future__ import annotations

from services import brand_report as br


def _row(kid, engine, found, status="completed", competitors=None):
    return {
        "keyword_id": kid, "engine": engine, "mention_found": found, "status": status,
        "competitor_results": competitors or [],
    }


def test_build_snapshot_aggregates_engines_overall_and_competitors():
    labels = {"k1": "burst pipe sydney"}
    rows = [
        _row("k1", "chatgpt", True, competitors=[{"name": "Rival", "found": False}]),
        _row("k1", "claude", False, competitors=[{"name": "Rival", "found": True}]),
        _row("k1", "gemini", None, status="failed"),  # excluded
    ]
    snap = br.build_snapshot(rows, labels)
    assert snap["overall"] == {"total": 2, "found": 1, "pct": 50.0}
    assert snap["engines"]["chatgpt"]["pct"] == 100.0
    assert snap["engines"]["claude"]["pct"] == 0.0
    # Failed gemini row isn't counted.
    assert snap["engines"]["gemini"]["total"] == 0
    assert snap["competitors"]["Rival"] == {"total": 2, "found": 1, "pct": 50.0}
    assert {"keyword": "burst pipe sydney", "engine": "claude"} in snap["invisible"]


def test_render_markdown_has_sections_and_marks():
    labels = {"k1": "burst pipe sydney"}
    rows = [
        _row("k1", "chatgpt", True),
        _row("k1", "claude", False, competitors=[{"name": "Rival", "found": True}]),
    ]
    snap = br.build_snapshot(rows, labels)
    md = br.render_markdown("Acme Plumbing", "1 Jul 2026", snap, narrative="Great progress.")
    assert "# AI Visibility Report — Acme Plumbing" in md
    assert "## Summary" in md and "Great progress." in md
    assert "## Visibility by engine" in md
    assert "burst pipe sydney" in md
    assert "✅" in md and "❌" in md
    assert "## Competitor comparison" in md and "Rival" in md


def test_render_markdown_omits_optional_sections_when_empty():
    snap = br.build_snapshot([], {})
    md = br.render_markdown("Acme", "1 Jul 2026", snap)
    assert "## Summary" not in md          # no narrative
    assert "Where you're invisible" not in md
    assert "Competitor comparison" not in md
