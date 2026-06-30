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


# ── reopt → unified mapping ──────────────────────────────────────────────────
def test_reopt_to_action_maps_organic_kind_to_category_and_role():
    a = {
        "kind": "cannibalization", "source": "organic", "keyword": "plumbing services",
        "recommendation": "Consolidate", "diagnosis": "3 pages split this query",
        "cta_path": "clients/c/gsc-research", "severity": "warning", "sort": 33_000,
    }
    out = se.reopt_to_action(a)
    assert out["module"] == "organic"
    assert out["category"] == "internal_link"      # cannibalization → consolidate
    assert out["assignee_role"] == "seo_tech"
    assert out["priority"] == 33_000               # reopt's cross-tier sort is preserved
    assert out["execution_mode"] == "assigned"
    assert out["target"]["severity"] == "warning"
    assert out["deep_link"] == "clients/c/gsc-research"
    assert out["title"] == "Resolve cannibalization: plumbing services"
    assert "3 pages split this query" in out["rationale"] and "Consolidate" in out["rationale"]


def test_reopt_to_action_maps_maps_source_to_maps_module():
    a = {"kind": "maps_decline", "source": "maps", "keyword": "roofing",
         "diagnosis": "Slipping", "cta_path": "clients/c/maps", "severity": "critical", "sort": 30_000}
    out = se.reopt_to_action(a)
    assert out["module"] == "maps" and out["category"] == "gbp"
    assert out["assignee_role"] == "account_manager"
    assert out["title"] == "Strengthen local pack: roofing"


def test_reopt_to_action_defaults_for_unknown_kind():
    out = se.reopt_to_action({"kind": "mystery", "source": "organic", "keyword": "x",
                              "cta_label": "Do it"})
    assert out["category"] == "page" and out["assignee_role"] == "writer"
    assert out["title"] == "Do it: x"              # falls back to cta_label template


# ── reader isolation + ordering ──────────────────────────────────────────────
def test_build_actions_isolates_failing_reader_and_sorts_by_priority():
    with patch.object(se, "_reopt_actions", side_effect=RuntimeError("boom")), \
         patch.object(se, "_llm_actions",
                      return_value=[{"module": "ai_visibility", "priority": 9, "target": {}}]):
        out = se.build_actions("c")  # no engagement_id → audit reader skipped
    # The reopt reader failed silently; the LLM reader survives.
    assert [a["module"] for a in out] == ["ai_visibility"]


def test_reopt_actions_delegates_to_gather_actions():
    raw = [
        {"kind": "rank_drop", "source": "organic", "keyword": "k1", "sort": 60_000,
         "severity": "warning", "cta_path": "p"},
        {"kind": "maps_weak_area", "source": "maps", "keyword": "Newtown", "sort": 31_000,
         "severity": "info", "cta_path": "m"},
    ]
    with patch.object(se.reopt_planner, "gather_actions", return_value=raw) as g:
        out = se._reopt_actions("c")
    g.assert_called_once_with("c")
    assert [a["module"] for a in out] == ["organic", "maps"]
    assert out[0]["title"] == "Fix ranking drop: k1"


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
