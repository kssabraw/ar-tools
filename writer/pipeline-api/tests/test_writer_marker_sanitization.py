"""Regression tests for citation-marker sanitization in Section writing.

Bug: when no citations are attached to an H2 group (or the LLM otherwise
hallucinates IDs), the section body contained `{{cit_001}}`-style markers
that don't exist in research.citations, and the Sources Cited module
would reject the run with HTTP 422 ("Markers reference unknown
citation_ids").
"""

from __future__ import annotations

from modules.writer.sections import _strip_invalid_markers


def test_strip_invalid_markers_drops_unknown_ids():
    body = "First fact.{{cit_001}} Second fact.{{cit_002}} End."
    out = _strip_invalid_markers(body, valid_ids=set())
    assert "{{cit_" not in out
    assert out == "First fact. Second fact. End."


def test_strip_invalid_markers_keeps_known_ids():
    body = "Real fact.{{cit_017}} Fake fact.{{cit_001}} End."
    out = _strip_invalid_markers(body, valid_ids={"cit_017"})
    assert "{{cit_017}}" in out
    assert "{{cit_001}}" not in out


def test_strip_invalid_markers_preserves_punctuation_spacing():
    body = "Fact one.{{cit_001}} Fact two.{{cit_002}}"
    out = _strip_invalid_markers(body, valid_ids=set())
    # No double spaces, no orphaned punctuation
    assert "  " not in out
    assert " ." not in out
    assert out == "Fact one. Fact two."


def test_strip_invalid_markers_no_op_when_all_valid():
    body = "Fact.{{cit_001}} More.{{cit_002}}"
    out = _strip_invalid_markers(body, valid_ids={"cit_001", "cit_002"})
    assert out == body


def test_strip_invalid_markers_handles_repeated_ids():
    body = "First.{{cit_001}} Second.{{cit_001}} Third.{{cit_001}}"
    out = _strip_invalid_markers(body, valid_ids=set())
    assert "{{cit_" not in out


def test_strip_invalid_markers_empty_body():
    assert _strip_invalid_markers("", valid_ids=set()) == ""


def test_strip_invalid_markers_no_markers_in_body():
    body = "Plain prose with no markers at all."
    out = _strip_invalid_markers(body, valid_ids=set())
    assert out == body


def test_strip_invalid_markers_mixed_known_and_unknown():
    body = (
        "Known cite.{{cit_010}} "
        "Invented one.{{cit_001}} "
        "Another known.{{cit_011}} "
        "Another invented.{{cit_999}}"
    )
    out = _strip_invalid_markers(body, valid_ids={"cit_010", "cit_011"})
    assert "{{cit_010}}" in out
    assert "{{cit_011}}" in out
    assert "{{cit_001}}" not in out
    assert "{{cit_999}}" not in out
