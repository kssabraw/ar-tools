"""Unit tests for services.strategy_engine — pure mappers + reader isolation."""

from __future__ import annotations

from unittest.mock import patch

from services import strategy_engine as se


# ── summarize ────────────────────────────────────────────────────────────────
def test_summarize_counts_headline_and_severity():
    actions = [
        {"module": "organic", "target": {"severity": "critical"}},
        {"module": "organic", "target": {"severity": "info"}},
        {"module": "maps", "target": {}},
        {"module": "ai_visibility", "target": {}},
    ]
    s = se.summarize(actions)
    assert s["action_count"] == 4
    assert s["counts"] == {"organic": 2, "maps": 1, "ai_visibility": 1}
    assert "2 organic" in s["headline"] and "1 Maps" in s["headline"] and "1 LLM" in s["headline"]
    assert s["severity"] == "critical"


def test_summarize_empty():
    s = se.summarize([])
    assert s["action_count"] == 0 and s["severity"] == "info"
    assert "healthy" in s["headline"]


# ── organic mapping ──────────────────────────────────────────────────────────
def test_organic_to_action_maps_kind_to_category_and_role():
    a = {
        "kind": "cannibalization", "keyword": "plumbing services",
        "recommendation": "Consolidate", "diagnosis": "3 pages split this query",
        "cta_path": "clients/c/gsc-research", "severity": "warning", "sort": 33_000,
    }
    out = se.organic_to_action("c", a)
    assert out["module"] == "organic"
    assert out["category"] == "internal_link"      # cannibalization → consolidate
    assert out["assignee_role"] == "seo_tech"
    assert out["priority"] == 33_000
    assert out["execution_mode"] == "assigned"
    assert out["target"]["severity"] == "warning"
    assert out["deep_link"] == "clients/c/gsc-research"


def test_organic_to_action_defaults_for_unknown_kind():
    out = se.organic_to_action("c", {"kind": "mystery", "keyword": "x"})
    assert out["category"] == "page" and out["assignee_role"] == "writer"
    assert out["title"] == "mystery"               # falls back to kind when no recommendation


# ── reader isolation + ordering ──────────────────────────────────────────────
def test_build_actions_isolates_failing_reader_and_sorts_by_priority():
    with patch.object(se, "_organic_actions",
                      return_value=[{"module": "organic", "priority": 5, "target": {}}]), \
         patch.object(se, "_maps_actions", side_effect=RuntimeError("boom")), \
         patch.object(se, "_llm_actions",
                      return_value=[{"module": "ai_visibility", "priority": 9, "target": {}}]):
        out = se.build_actions("c")
    # Maps failed silently; the other two survive, sorted by priority desc.
    assert [a["module"] for a in out] == ["ai_visibility", "organic"]
