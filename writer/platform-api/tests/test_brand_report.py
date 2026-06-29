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
    assert any(i["keyword"] == "burst pipe sydney" and i["engine"] == "claude" for i in snap["invisible"])


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


def _rich_row(kid, engine, found, *, diagnosis=None, ra=None, status="completed"):
    return {
        "keyword_id": kid, "engine": engine, "mention_found": found, "status": status,
        "competitor_results": [], "invisibility_diagnosis": diagnosis, "response_analysis": ra,
    }


def test_build_snapshot_mines_response_analysis_enrichment():
    labels = {"k1": "emergency plumber"}
    rows = [
        _rich_row("k1", "chatgpt", False, diagnosis="You have few reviews vs competitors.",
                  ra={"accuracy_flags": [{"field": "phone", "stated": "111", "actual": "222"}],
                      "discovered_competitors": [{"name": "New Co", "attributes": ["24/7"]}],
                      "sources": {"by_type": {"directory": 2}},
                      "competitor_attributes": [{"name": "Rival", "attributes": ["fast"]}]}),
        _rich_row("k1", "google_ai_overview", True,
                  ra={"prominence": "leading", "aio": {"mention_kind": "in_content_link"},
                      "sources": {"by_type": {"directory": 1, "review": 1}}}),
    ]
    snap = br.build_snapshot(rows, labels)
    # Invisible cell carries its diagnosis.
    inv = next(i for i in snap["invisible"] if i["engine"] == "chatgpt")
    assert inv["diagnosis"] == "You have few reviews vs competitors."
    # Misinformation, AIO link status, standout mention, discovered competitor, sources.
    assert snap["accuracy"][0]["field"] == "phone"
    assert snap["aio"][0]["kind"] == "in_content_link"
    assert {"keyword": "emergency plumber", "engine": "google_ai_overview"} in snap["leading"]
    assert snap["discovered"][0]["name"] == "New Co"
    assert snap["source_types"] == {"directory": 3, "review": 1}


def test_render_markdown_renders_enrichment_sections():
    labels = {"k1": "emergency plumber"}
    rows = [
        _rich_row("k1", "chatgpt", False, diagnosis="Few reviews; weak backlinks.",
                  ra={"accuracy_flags": [{"field": "status", "stated": "permanently closed", "actual": "open"}],
                      "discovered_competitors": [{"name": "New Co", "attributes": ["24/7"]}],
                      "sources": {"by_type": {"directory": 2}}}),
        _rich_row("k1", "google_ai_overview", False, diagnosis="Not in the AI Overview.",
                  ra={"aio": {"mention_kind": "citation_only"}}),
    ]
    snap = br.build_snapshot(rows, labels)
    md = br.render_markdown("Acme", "1 Jul 2026", snap)
    assert "## ⚠ Possible misinformation" in md and "permanently closed" in md
    assert "## Where you're invisible & why" in md and "Few reviews; weak backlinks." in md
    assert "## Google AI Overview presence" in md and "cited in the sources strip only" in md
    assert "## Competitors the AIs surfaced (not yet tracked)" in md and "New Co" in md
    assert "## Where the AIs get their information" in md and "Directories" in md


def test_render_markdown_caps_diagnoses(monkeypatch):
    monkeypatch.setattr(br, "_MAX_DIAGNOSES", 1)
    labels = {f"k{i}": f"kw{i}" for i in range(3)}
    rows = [_rich_row(f"k{i}", "chatgpt", False, diagnosis=f"reason {i}") for i in range(3)]
    md = br.render_markdown("Acme", "1 Jul 2026", br.build_snapshot(rows, labels))
    # Only the first keyword's diagnosis prose is included; all still listed.
    assert md.count("reason ") == 1
    assert md.count("Not shown by:") == 3


def test_cell_escapes_pipes_and_flattens_newlines():
    assert br._cell("a|b\nc") == "a\\|b c"


def test_render_markdown_escapes_pipe_in_keyword():
    snap = br.build_snapshot([_row("k1", "chatgpt", True)], {"k1": "a|b plumbing"})
    md = br.render_markdown("Acme", "1 Jul 2026", snap)
    assert "a\\|b plumbing" in md and "| a|b plumbing |" not in md


def test_render_markdown_omits_optional_sections_when_empty():
    snap = br.build_snapshot([], {})
    md = br.render_markdown("Acme", "1 Jul 2026", snap)
    assert "## Summary" not in md          # no narrative
    assert "Where you're invisible" not in md
    assert "Competitor comparison" not in md
