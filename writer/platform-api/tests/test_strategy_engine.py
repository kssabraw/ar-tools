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


def test_backlink_audit_action_uses_distinct_kind_from_authority_gap():
    # Prospect list must NOT collide with reopt_planner's authority-gap kind.
    actions = se.backlink_audit_actions({"gap_count": 2, "gaps": [
        {"referring_domain": "a.com"}, {"referring_domain": "b.com"}]})
    assert actions[0]["kind"] == "backlink_prospects"


# ── LLM actions (reuse brand_alerts diff logic) ──────────────────────────────
def _idx(cells, misinfo=None):
    """Minimal index_batch-shaped dict for build_llm_actions tests."""
    return {"cells": cells, "misinfo": misinfo or []}


def test_build_llm_actions_invisible_everywhere_is_a_standing_gap():
    curr = _idx({("k1", "chatgpt"): False, ("k1", "claude"): False})
    out = se.build_llm_actions("c", curr, None, {"k1": "roof repair"})
    assert len(out) == 1
    assert out[0]["kind"] == "llm_content_gap"
    assert out[0]["target"]["severity"] == "warning"
    assert "roof repair" in out[0]["title"]


def test_build_llm_actions_regression_when_engine_goes_dark():
    prev = _idx({("k1", "chatgpt"): True, ("k1", "claude"): True})
    curr = _idx({("k1", "chatgpt"): True, ("k1", "claude"): False})  # lost claude, still visible
    out = se.build_llm_actions("c", curr, prev, {"k1": "plumber"})
    kinds = [a["kind"] for a in out]
    assert "llm_regression" in kinds
    reg = next(a for a in out if a["kind"] == "llm_regression")
    assert reg["priority"] > 120  # regressions outrank standing gaps


def test_build_llm_actions_misinfo_is_critical_and_ranks_first():
    prev = _idx({("k1", "chatgpt"): True})
    curr = _idx({("k1", "chatgpt"): True},
                misinfo=[{"keyword_id": "k1", "engine": "chatgpt", "field": "phone",
                          "stated": "111", "actual": "222"}])
    out = se.build_llm_actions("c", curr, prev, {"k1": "dentist"})
    assert out[0]["kind"] == "llm_misinfo"
    assert out[0]["target"]["severity"] == "critical"


def test_build_llm_actions_regression_superseded_by_full_invisibility():
    # k1 was fully visible, now fully invisible → one standing-gap action, no
    # duplicate regression action for the same keyword.
    prev = _idx({("k1", "chatgpt"): True, ("k1", "claude"): True})
    curr = _idx({("k1", "chatgpt"): False, ("k1", "claude"): False})
    out = se.build_llm_actions("c", curr, prev, {"k1": "roofer"})
    assert [a["kind"] for a in out] == ["llm_content_gap"]
