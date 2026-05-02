"""Regression tests for the empty Sources Cited section suppression and the
writer's global-citations fallback.
"""

from __future__ import annotations

from modules.sources_cited.entries import build_sources_cited_sections


def test_empty_citations_suppresses_sources_cited_sections():
    """When no citations were placed in the body, ordered_used_citations
    is empty — building Sources Cited should return zero sections rather
    than emit `<ol class="sources-cited"></ol>` with no entries.
    """
    sections, flags = build_sources_cited_sections(
        ordered_used_citations=[],
        citations_by_id={},
        conclusion_order=10,
    )
    assert sections == []
    assert flags["entries_with_missing_publication"] == []
    assert flags["entries_with_placeholder"] == []


def test_non_empty_citations_still_renders_sections():
    """Unchanged behavior: when at least one citation was used, both the
    header and body sections are emitted with the rendered list."""
    citations_by_id = {
        "cit_001": {
            "citation_id": "cit_001",
            "title": "Example",
            "url": "https://example.com",
            "publication_date": "2025-01-01",
            "site_name": "Example",
        },
    }
    sections, _ = build_sources_cited_sections(
        ordered_used_citations=["cit_001"],
        citations_by_id=citations_by_id,
        conclusion_order=10,
    )
    assert len(sections) == 2
    assert sections[0]["type"] == "sources-cited-header"
    assert sections[1]["type"] == "sources-cited-body"
    assert "<ol class=\"sources-cited\">" in sections[1]["body"]
    assert "cit_001" not in sections[1]["body"]  # rendered as numbered entry, not raw id
