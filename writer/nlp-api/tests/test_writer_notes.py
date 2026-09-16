"""Tests for the supplementary writer-notes prompt block (`main._writer_notes_block`)
and the `ReoptimizePageRequest.writer_notes` field it reads — the nlp-api half of
the Content Gap Analyzer's reoptimize handoff (§11.1): platform-api threads a
compact gap-notes string through the reopt path, and nlp renders it as advisory,
additive rewrite guidance — never as a scored deficiency."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def test_block_renders_notes_as_advisory_not_a_deficiency():
    block = main._writer_notes_block(
        "Content-gap analysis — cover these subtopics: cost factors; permits; timeline."
    )
    assert block.startswith("\nSUPPLEMENTARY GUIDANCE")
    assert "NOT a scored deficiency" in block
    assert "cost factors; permits; timeline." in block
    # It must not present itself as a deficiency to fix.
    assert "DEFICIENCIES" not in block


def test_block_empty_when_no_notes():
    assert main._writer_notes_block(None) == ""
    assert main._writer_notes_block("") == ""
    assert main._writer_notes_block("   \n  ") == ""


def test_block_truncates_overlong_notes():
    long = "x" * (main._WRITER_NOTES_MAX_CHARS + 500)
    block = main._writer_notes_block(long)
    assert block.endswith("…\n")
    # The rendered notes body never exceeds the cap (+ the single ellipsis).
    assert block.count("x") <= main._WRITER_NOTES_MAX_CHARS


def test_reoptimize_request_accepts_writer_notes():
    reopt = main.ReoptimizePageRequest(
        keyword="k", location="l", deficiencies=[], business_name="b", gbp_category="c",
        writer_notes="cover the subtopics competitors address",
    )
    assert reopt.writer_notes == "cover the subtopics competitors address"
    # Default stays None so every existing caller is untouched.
    assert main.ReoptimizePageRequest(
        keyword="k", location="l", deficiencies=[], business_name="b", gbp_category="c",
    ).writer_notes is None
