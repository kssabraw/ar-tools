"""Unit tests for the per-section voice-drift localizer's pure instruction
builder (`main._build_drift_block`).

Covers the deterministic half of Lever 2: turning a Haiku per-section audit into
the targeted corrective-prompt block, with the guards that keep a hallucinated or
malformed audit from corrupting the prompt (unknown keys dropped, dedupe, 6 cap,
empty → "" so the caller falls back to the page-wide sweep). Pure + offline — no
network, no Anthropic. Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


_KEYS = {"intro", "services", "why-us", "areas", "faq"}


def test_builds_targeted_block_from_object_form():
    drift = {
        "drift": [
            {"key": "services", "dimensions": ["register", "rhythm"],
             "note": "bare bullet list, clipped"},
            {"key": "areas", "dimensions": ["distinctiveness"], "note": "generic"},
        ]
    }
    block = main._build_drift_block(drift, _KEYS)
    assert "[services]" in block
    assert "register, rhythm" in block
    assert "bare bullet list" in block
    assert "[areas]" in block
    # The intro/faq (not flagged) never appear.
    assert "[intro]" not in block
    assert "[faq]" not in block


def test_accepts_bare_list_form():
    drift = [{"key": "services", "dimensions": ["register"], "note": "flat"}]
    block = main._build_drift_block(drift, _KEYS)
    assert "[services]" in block


def test_drops_unknown_keys_and_dedupes():
    drift = {
        "drift": [
            {"key": "ghost", "dimensions": ["tone"], "note": "hallucinated"},
            {"key": "services", "dimensions": ["register"], "note": "one"},
            {"key": "services", "dimensions": ["rhythm"], "note": "dupe"},
        ]
    }
    block = main._build_drift_block(drift, _KEYS)
    assert "ghost" not in block
    # services appears exactly once (dedupe keeps the first).
    assert block.count("[services]") == 1
    assert "one" in block and "dupe" not in block


def test_caps_at_six_sections():
    keys = {f"s{i}" for i in range(10)}
    drift = {"drift": [{"key": f"s{i}", "dimensions": ["register"]} for i in range(10)]}
    block = main._build_drift_block(drift, keys)
    assert block.count("  [s") == 6


def test_empty_or_no_matches_returns_empty_string():
    assert main._build_drift_block({"drift": []}, _KEYS) == ""
    assert main._build_drift_block({"drift": [{"key": "ghost"}]}, _KEYS) == ""
    assert main._build_drift_block(None, _KEYS) == ""
    assert main._build_drift_block({"nope": 1}, _KEYS) == ""


def test_missing_dimensions_or_note_still_renders_key():
    block = main._build_drift_block({"drift": [{"key": "services"}]}, _KEYS)
    assert "[services]" in block
