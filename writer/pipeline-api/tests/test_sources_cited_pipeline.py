"""Sources Cited pipeline tests.

No external APIs to mock - module is fully deterministic.
"""

from __future__ import annotations

import pytest

from models.sources_cited import SourcesCitedRequest


WRITER_OUTPUT = {
    "keyword": "best hvac systems 2026",
    "intent_type": "informational-commercial",
    "title": "Best HVAC Systems 2026",
    "article": [
        {"order": 1, "level": "H1", "type": "content", "heading": "best hvac systems 2026", "body": "", "word_count": 0, "section_budget": 0, "citations_referenced": []},
        {"order": 2, "level": "H2", "type": "content", "heading": "Energy Efficiency Ratings",
         "body": "Modern HVAC systems can be 50% more efficient.{{cit_003}} Heat pumps are widely recommended.{{cit_007}}",
         "word_count": 12, "section_budget": 200, "citations_referenced": ["cit_003", "cit_007"]},
        {"order": 3, "level": "H3", "type": "content", "heading": "Hidden costs",
         "body": "Installation fees vary by region.{{cit_001}}{{cit_007}}",
         "word_count": 7, "section_budget": 150, "citations_referenced": ["cit_001", "cit_007"]},
        {"order": 4, "level": "H2", "type": "content", "heading": "Top Brands",
         "body": "Carrier, Trane, and Lennox are top-rated. No marker here.",
         "word_count": 9, "section_budget": 200, "citations_referenced": []},
        {"order": 5, "level": "H2", "type": "faq-header", "heading": "Frequently Asked Questions", "body": "", "word_count": 0, "section_budget": 0, "citations_referenced": []},
        {"order": 6, "level": "H3", "type": "faq-question", "heading": "How long does an HVAC system last?", "body": "Most last 15-20 years.", "word_count": 4, "section_budget": 0, "citations_referenced": []},
        {"order": 7, "level": "none", "type": "conclusion", "heading": None,
         "body": "Choosing the best hvac systems 2026 depends on climate and budget.",
         "word_count": 11, "section_budget": 125, "citations_referenced": []},
    ],
    "citation_usage": {
        "total_citations_available": 4,
        "citations_used": 3,
        "citations_unused": 1,
        "usage": [
            {"citation_id": "cit_003", "used": True, "sections_used_in": [2], "marker_placed": True},
            {"citation_id": "cit_007", "used": True, "sections_used_in": [2, 3], "marker_placed": True},
            {"citation_id": "cit_001", "used": True, "sections_used_in": [3], "marker_placed": True},
            {"citation_id": "cit_999", "used": False, "sections_used_in": [], "marker_placed": False},
        ],
    },
    "format_compliance": {},
    "metadata": {"schema_version": "1.7", "brief_schema_version": "1.7"},
}


RESEARCH_OUTPUT = {
    "keyword": "best hvac systems 2026",
    "citations": [
        {"citation_id": "cit_001", "url": "https://www.energy.gov/hvac-installation",
         "title": "HVAC Installation Costs", "publication": "Department of Energy", "tier": 1},
        {"citation_id": "cit_003", "url": "https://www.consumerreports.org/hvac",
         "title": "Best HVAC Systems Compared", "publication": "Consumer Reports", "tier": 2},
        {"citation_id": "cit_007", "url": "https://www.energystar.gov/heat-pumps",
         "title": "Heat Pump Buying Guide", "publication": "ENERGY STAR", "tier": 1},
        {"citation_id": "cit_999", "url": "https://example.com/unused",
         "title": "Unused Citation", "publication": "Example", "tier": 3},
    ],
}


def test_happy_path_with_stacked_marker_sort():
    from modules.sources_cited.pipeline import run_sources_cited

    req = SourcesCitedRequest(
        run_id="t",
        writer_output=WRITER_OUTPUT,
        research_output=RESEARCH_OUTPUT,
    )
    result = run_sources_cited(req)
    md = result.sources_cited_metadata

    # First-appearance numbering: cit_003 → 1, cit_007 → 2, cit_001 → 3
    assert md.citation_number_map == {"cit_003": 1, "cit_007": 2, "cit_001": 3}
    assert md.total_citations_in_sources_cited == 3

    article = result.enriched_article["article"]
    section_3_body = next(s for s in article if s["order"] == 3)["body"]

    # Stacked markers in source order {{cit_001}}{{cit_007}} should be
    # rendered as [2][3] (cit_007=2 ascending before cit_001=3)
    assert "sources-cited-2" in section_3_body
    assert "sources-cited-3" in section_3_body
    # Verify ordering: cit_007 superscript appears before cit_001 superscript
    sup2_pos = section_3_body.find("sources-cited-2")
    sup3_pos = section_3_body.find("sources-cited-3")
    assert sup2_pos < sup3_pos

    # Sources Cited section appended after conclusion (order 7 → 8 + 9)
    sc_header = next(s for s in article if s["type"] == "sources-cited-header")
    sc_body = next(s for s in article if s["type"] == "sources-cited-body")
    assert sc_header["order"] == 8
    assert sc_body["order"] == 9
    assert sc_header["heading"] == "Sources Cited"

    # rel="nofollow" on every external link
    assert sc_body["body"].count('rel="nofollow"') == 3

    # cit_999 (used:False) excluded; orphans empty (no used:true without marker)
    assert "cit_999" not in md.citation_number_map
    assert md.orphaned_usage_records == []

    # Schema version bookkeeping
    assert md.schema_version == "1.1"
    assert md.writer_schema_version == "1.7"


def test_aborts_on_marker_in_heading():
    from modules.sources_cited.pipeline import SourcesCitedError, run_sources_cited

    bad_writer = dict(WRITER_OUTPUT)
    bad_writer["article"] = list(WRITER_OUTPUT["article"])
    bad_writer["article"][1] = dict(bad_writer["article"][1])
    bad_writer["article"][1]["heading"] = "Energy Efficiency {{cit_003}} Ratings"

    req = SourcesCitedRequest(run_id="t", writer_output=bad_writer, research_output=RESEARCH_OUTPUT)
    with pytest.raises(SourcesCitedError) as exc_info:
        run_sources_cited(req)
    assert exc_info.value.code == "marker_in_heading"


def test_strips_unresolvable_markers_and_continues():
    """Hallucinated citation_ids that don't exist in research.citations
    are stripped from the body (not aborted on). The strip is recorded
    in sources_cited_metadata.unresolvable_markers_stripped."""
    from modules.sources_cited.pipeline import run_sources_cited

    bad_writer = dict(WRITER_OUTPUT)
    bad_writer["article"] = [dict(s) for s in WRITER_OUTPUT["article"]]
    # cit_042 is NOT in RESEARCH_OUTPUT.citations - simulates the writer
    # hallucinating a sequential ID like cit_001..cit_009.
    bad_writer["article"][1]["body"] = (
        bad_writer["article"][1]["body"] + " Hallucinated.{{cit_042}}"
    )

    req = SourcesCitedRequest(run_id="t", writer_output=bad_writer, research_output=RESEARCH_OUTPUT)
    result = run_sources_cited(req)

    # The run completed (no abort)
    assert result.sources_cited_metadata.unresolvable_markers_stripped == ["cit_042"]
    # The marker is gone from the rendered body
    rendered_body = result.enriched_article["article"][1]["body"]
    assert "{{cit_042}}" not in rendered_body
    assert "cit_042" not in result.sources_cited_metadata.citation_number_map


def test_logs_writer_integrity_violation_and_continues():
    """Marker in prose with citation_id not present in citation_usage -
    logged as a structured warning + reported in metadata, run completes."""
    from modules.sources_cited.pipeline import run_sources_cited

    bad_writer = dict(WRITER_OUTPUT)
    bad_writer["citation_usage"] = dict(WRITER_OUTPUT["citation_usage"])
    # Remove cit_003 from usage tracking but leave the marker in prose
    bad_writer["citation_usage"]["usage"] = [
        u for u in WRITER_OUTPUT["citation_usage"]["usage"]
        if u["citation_id"] != "cit_003"
    ]
    req = SourcesCitedRequest(run_id="t", writer_output=bad_writer, research_output=RESEARCH_OUTPUT)
    result = run_sources_cited(req)

    assert "cit_003" in result.sources_cited_metadata.integrity_violations
    # cit_003 still gets numbered and rendered (it's a real citation)
    assert "cit_003" in result.sources_cited_metadata.citation_number_map


def test_aborts_on_keyword_mismatch():
    from modules.sources_cited.pipeline import SourcesCitedError, run_sources_cited

    bad_research = dict(RESEARCH_OUTPUT)
    bad_research["keyword"] = "completely different topic"
    req = SourcesCitedRequest(run_id="t", writer_output=WRITER_OUTPUT, research_output=bad_research)
    with pytest.raises(SourcesCitedError) as exc_info:
        run_sources_cited(req)
    assert exc_info.value.code == "keyword_mismatch"


def test_aborts_on_old_writer_schema():
    from modules.sources_cited.pipeline import SourcesCitedError, run_sources_cited

    bad_writer = dict(WRITER_OUTPUT)
    bad_writer["metadata"] = dict(WRITER_OUTPUT["metadata"])
    bad_writer["metadata"]["schema_version"] = "1.3"
    req = SourcesCitedRequest(run_id="t", writer_output=bad_writer, research_output=RESEARCH_OUTPUT)
    with pytest.raises(SourcesCitedError) as exc_info:
        run_sources_cited(req)
    assert exc_info.value.code == "writer_schema_too_old"


def test_orphaned_usage_record_flagged_not_aborting():
    """citation_usage.usage[].used=True with no marker in prose → flagged but not aborted."""
    from modules.sources_cited.pipeline import run_sources_cited

    bad_writer = dict(WRITER_OUTPUT)
    bad_writer["citation_usage"] = dict(WRITER_OUTPUT["citation_usage"])
    bad_writer["citation_usage"]["usage"] = list(WRITER_OUTPUT["citation_usage"]["usage"])
    # Mark cit_999 as used:True even though no marker exists
    bad_writer["citation_usage"]["usage"][3] = {
        "citation_id": "cit_999", "used": True, "sections_used_in": [], "marker_placed": False
    }
    req = SourcesCitedRequest(run_id="t", writer_output=bad_writer, research_output=RESEARCH_OUTPUT)
    result = run_sources_cited(req)
    assert "cit_999" in result.sources_cited_metadata.orphaned_usage_records
    # Orphan excluded from Sources Cited
    assert "cit_999" not in result.sources_cited_metadata.citation_number_map


def test_publication_fallback_to_root_domain():
    from modules.sources_cited.entries import render_entry

    citation = {
        "citation_id": "cit_001",
        "title": "A Page Title",
        "url": "https://www.example.com/some/path",
        # publication missing
    }
    body, flags, used_placeholder = render_entry(citation)
    assert "example.com" in body
    assert "entries_with_missing_publication" in flags
    assert not used_placeholder


def test_placeholder_when_title_or_url_missing():
    from modules.sources_cited.entries import render_entry

    no_title = {"citation_id": "cit_x", "url": "https://x.com", "publication": "X"}
    body, flags, placeholder = render_entry(no_title)
    assert placeholder
    assert "Citation data unavailable" in body
    assert "entries_with_placeholder" in flags

    no_url = {"citation_id": "cit_y", "title": "Y", "publication": "Y"}
    _, flags2, p2 = render_entry(no_url)
    assert p2
    assert "entries_with_placeholder" in flags2


def test_request_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SourcesCitedRequest(run_id="r", writer_output="not a dict", research_output={})
