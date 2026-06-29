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
        out = se.build_actions("c")  # no engagement_id → audit reader skipped
    # Maps failed silently; the other two survive, sorted by priority desc.
    assert [a["module"] for a in out] == ["ai_visibility", "organic"]


# ── audit → action mappers ───────────────────────────────────────────────────
def test_site_audit_actions_group_issues_by_type():
    result = {"issues": [
        {"type": "missing_title", "severity": "high", "detail": "No title", "url": "a"},
        {"type": "missing_title", "severity": "high", "detail": "No title", "url": "b"},
        {"type": "image_alt", "severity": "low", "detail": "Missing alt", "url": "a"},
    ]}
    actions = se.site_audit_actions(result)
    titles = {a["title"] for a in actions}
    assert any("No title (2 pages)" in t for t in titles)
    assert all(a["module"] == "cross" and a["category"] == "technical_fix" for a in actions)
    # higher severity × count sorts first
    assert actions[0]["kind"] == "technical_fix" and actions[0]["priority"] == 16  # high(8)×2


def test_backlink_audit_actions_single_prospect_list():
    result = {"gap_count": 3, "gaps": [
        {"referring_domain": "news.com", "competitors_linking": 3},
        {"referring_domain": "blog.com", "competitors_linking": 2},
    ]}
    actions = se.backlink_audit_actions(result)
    assert len(actions) == 1
    assert actions[0]["module"] == "organic" and actions[0]["assignee_role"] == "link_builder"
    assert "news.com" in actions[0]["rationale"]
    assert se.backlink_audit_actions({"gaps": []}) == []


def test_citation_audit_actions_lists_missing():
    actions = se.citation_audit_actions({"missing": ["yelp.com", "bbb.org"]})
    assert len(actions) == 1
    assert actions[0]["module"] == "maps" and actions[0]["category"] == "citation"
    assert actions[0]["priority"] == 10  # 2 missing × 5
    assert se.citation_audit_actions({"missing": []}) == []
