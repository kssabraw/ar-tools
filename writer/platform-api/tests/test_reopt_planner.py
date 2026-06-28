"""Unit tests for the reoptimization planner pure helpers (no network)."""

from __future__ import annotations

from services import reopt_planner


CLIENT = "11111111-1111-1111-1111-111111111111"


def _rankability_item(**over):
    base = {
        "keyword": "emergency plumber",
        "has_snapshot": True,
        "score": 70,
        "band": "Easy",
        "priority": 5000.0,
        "client_rank": 12,
        "est_value": 1200,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# build_actions
# ---------------------------------------------------------------------------
def test_drop_outranks_everything_and_deindex_is_critical():
    drops = [
        {"keyword": "blocked drain", "alert_type": "drop", "message": "Fell 8 spots."},
        {"keyword": "burst pipe", "alert_type": "deindexed", "message": "Page deindexed."},
    ]
    actions = reopt_planner.build_actions(CLIENT, drops, [], {})
    assert len(actions) == 2
    # deindex sorts above an ordinary drop, and is critical with the indexing CTA.
    first = actions[0]
    assert first["keyword"] == "burst pipe"
    assert first["kind"] == "rank_drop"
    assert first["severity"] == "critical"
    assert "URL Inspection" in first["recommendation"]
    assert actions[1]["severity"] == "warning"
    assert all(a["cta_path"] == f"clients/{CLIENT}/rankings" for a in actions)


def test_quick_win_striking_distance_reoptimizes_else_creates():
    items = [
        _rankability_item(keyword="hot water repair", client_rank=8, priority=9000.0),
        _rankability_item(keyword="gas fitting", client_rank=None, priority=8000.0),
    ]
    actions = reopt_planner.build_actions(CLIENT, [], items, {})
    by_kw = {a["keyword"]: a for a in actions}
    assert by_kw["hot water repair"]["cta_label"] == "Reoptimize"
    assert "#8" in by_kw["hot water repair"]["recommendation"]
    assert by_kw["gas fitting"]["cta_label"] == "Create page"
    assert all(a["cta_path"] == f"clients/{CLIENT}/local-seo" for a in actions)


def test_quick_win_excludes_low_score_wrong_band_and_no_snapshot():
    items = [
        _rankability_item(keyword="a", band="Hard"),                 # wrong band
        _rankability_item(keyword="b", score=40),                    # below min score
        _rankability_item(keyword="c", has_snapshot=False, score=None, band=None),  # no snapshot
        _rankability_item(keyword="d", score=80, band="Moderate"),   # kept
    ]
    actions = reopt_planner.build_actions(CLIENT, [], items, {})
    kws = {a["keyword"] for a in actions}
    assert kws == {"d"}


def test_drop_supersedes_quick_win_for_same_keyword():
    drops = [{"keyword": "Emergency Plumber", "alert_type": "drop", "message": "Dropped."}]
    items = [_rankability_item(keyword="emergency plumber")]
    actions = reopt_planner.build_actions(CLIENT, drops, items, {})
    kinds = {a["keyword"].lower(): a["kind"] for a in actions}
    assert kinds == {"emergency plumber": "rank_drop"}  # case-insensitive dedup


def test_gsc_cannibalization_and_hidden_wins_mapped():
    gsc = {
        "cannibalization": [{"query": "drain cleaning", "page_count": 3, "total_impressions": 4200}],
        "hidden_wins": [{"keyword": "leak detection", "position": 14.0, "impressions": 300}],
    }
    actions = reopt_planner.build_actions(CLIENT, [], [], gsc)
    by_kind = {a["kind"]: a for a in actions}
    assert by_kind["cannibalization"]["keyword"] == "drain cleaning"
    assert "3 pages" in by_kind["cannibalization"]["diagnosis"]
    assert by_kind["cannibalization"]["cta_path"] == f"clients/{CLIENT}/gsc-research"
    assert by_kind["opportunity"]["keyword"] == "leak detection"
    assert "page 2" in by_kind["opportunity"]["diagnosis"]


def test_hidden_win_skipped_when_already_a_drop():
    drops = [{"keyword": "leak detection", "alert_type": "drop", "message": "Dropped."}]
    gsc = {"hidden_wins": [{"keyword": "leak detection", "position": 14.0, "impressions": 300}]}
    actions = reopt_planner.build_actions(CLIENT, drops, [], gsc)
    assert [a["kind"] for a in actions] == ["rank_drop"]


def test_total_capped():
    drops = [
        {"keyword": f"kw{i}", "alert_type": "drop", "message": "d"} for i in range(40)
    ]
    actions = reopt_planner.build_actions(CLIENT, drops, [], {})
    assert len(actions) == reopt_planner.TOTAL_MAX


def test_ordering_drops_then_cannibal_then_quick_then_hidden():
    drops = [{"keyword": "d1", "alert_type": "drop", "message": "x"}]
    items = [_rankability_item(keyword="q1", priority=10.0)]
    gsc = {
        "cannibalization": [{"query": "c1", "page_count": 2, "total_impressions": 10}],
        "hidden_wins": [{"keyword": "h1", "position": 15.0, "impressions": 5}],
    }
    actions = reopt_planner.build_actions(CLIENT, drops, items, gsc)
    order = [a["keyword"] for a in actions]
    assert order[0] == "d1"          # drop (1000) first
    assert order.index("c1") < order.index("q1")  # cannibal (800) before low-priority quick win
    assert order[-1] == "h1"         # hidden win (impressions=5) last


def test_high_value_quick_win_never_leapfrogs_a_drop():
    # A huge-priority quick win must still sort below an ordinary drop (strict tiers).
    drops = [{"keyword": "d1", "alert_type": "drop", "message": "x"}]
    items = [_rankability_item(keyword="q1", priority=999_999.0, est_value=999_999)]
    actions = reopt_planner.build_actions(CLIENT, drops, items, {})
    assert actions[0]["keyword"] == "d1"
    assert actions[0]["sort"] > actions[1]["sort"]


def test_cannibalization_rows_rank_by_impressions():
    gsc = {
        "cannibalization": [
            {"query": "low", "page_count": 2, "total_impressions": 100},
            {"query": "high", "page_count": 2, "total_impressions": 9000},
        ],
    }
    actions = reopt_planner.build_actions(CLIENT, [], [], gsc)
    assert [a["keyword"] for a in actions] == ["high", "low"]


# ---------------------------------------------------------------------------
# summarize_plan
# ---------------------------------------------------------------------------
def test_summarize_empty():
    out = reopt_planner.summarize_plan([])
    assert out["severity"] == "info"
    assert "healthy" in out["summary"]


def test_summarize_counts_and_severity():
    actions = [
        {"kind": "rank_drop", "severity": "critical"},
        {"kind": "rank_drop", "severity": "warning"},
        {"kind": "quick_win", "severity": "info"},
        {"kind": "cannibalization", "severity": "warning"},
        {"kind": "opportunity", "severity": "info"},
    ]
    out = reopt_planner.summarize_plan(actions)
    assert out["severity"] == "critical"
    assert "2 drops to fix" in out["summary"]
    assert "1 quick win" in out["summary"]
    assert "2 other opportunities" in out["summary"]


# ---------------------------------------------------------------------------
# _should_store (empty-plan dedup)
# ---------------------------------------------------------------------------
def test_should_store_nonempty_always():
    assert reopt_planner._should_store(3, None) is True
    assert reopt_planner._should_store(3, 0) is True
    assert reopt_planner._should_store(3, 5) is True


def test_should_store_first_empty_when_no_prior():
    assert reopt_planner._should_store(0, None) is True   # record the first empty


def test_should_store_records_transition_to_empty():
    assert reopt_planner._should_store(0, 2) is True       # actions cleared → store


def test_should_skip_steady_state_empty():
    assert reopt_planner._should_store(0, 0) is False      # empty after empty → skip


def test_summarize_singular_plurals():
    out = reopt_planner.summarize_plan([
        {"kind": "rank_drop", "severity": "warning"},
        {"kind": "quick_win", "severity": "info"},
        {"kind": "opportunity", "severity": "info"},
    ])
    assert "1 drop to fix" in out["summary"]
    assert "1 quick win" in out["summary"]
    assert "1 other opportunity" in out["summary"]
    assert out["severity"] == "warning"
