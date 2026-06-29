"""Unit tests for the SOP store's pure budgeting/formatting helpers."""

from services import sop_store


def test_format_sops_merges_both_layers():
    agency = [{"title": "Reopt SOP", "category": "reoptimization", "content": "reoptimize fully"}]
    client = [{"title": "Client note", "category": "local", "content": "this client prefers X"}]
    out = sop_store._format_sops(agency, client, 24_000)
    assert "AGENCY-WIDE PLAYBOOK & THEORIES" in out
    assert "CLIENT-SPECIFIC SOPs (take precedence)" in out
    assert "Reopt SOP" in out and "Client note" in out
    # Per-client block comes last (highest precedence).
    assert out.index("AGENCY-WIDE") < out.index("CLIENT-SPECIFIC")


def test_format_sops_empty_when_no_rows():
    assert sop_store._format_sops([], [], 24_000) == ""


def test_format_sops_skips_blank_content():
    agency = [{"title": "Empty", "category": "general", "content": "   "}]
    assert sop_store._format_sops(agency, [], 24_000) == ""


def test_format_sops_keeps_client_block_under_tight_budget():
    agency = [{"title": "Big", "category": "general", "content": "word " * 500}]
    client = [{"title": "Keep me", "category": "local", "content": "must survive"}]
    out = sop_store._format_sops(agency, client, 80)
    assert "Keep me" in out and "must survive" in out


def test_truncate_word_boundary_and_marker():
    out = sop_store._truncate("one two three four five", 12)
    assert out.startswith("one two")
    assert "[truncated]" in out
    # Under the limit → returned unchanged.
    assert sop_store._truncate("short", 100) == "short"
