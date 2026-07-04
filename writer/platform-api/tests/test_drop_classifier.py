"""Unit tests for services.drop_classifier — the pure B1–B5 classification
layer from the Organic Rank Drop SOP (docs/sops/Rank_Drop_Mitigation_SOP_Organic.md).

No network / no DB: only the pure helpers plus the planner integration
(build_actions with classified drops) are exercised; classify_client_drops'
reads are covered by integration testing.
"""

from __future__ import annotations

from services import drop_classifier as dc
from services.reopt_planner import build_actions, build_sitewide_action


# ---------------------------------------------------------------------------
# detect_scope — sitewide (§A) vs specific (§B)
# ---------------------------------------------------------------------------
def test_scope_sitewide_by_count():
    assert dc.detect_scope(5, 100) == "sitewide"


def test_scope_sitewide_by_share():
    assert dc.detect_scope(3, 10) == "sitewide"  # 30% of tracked


def test_scope_specific():
    assert dc.detect_scope(2, 40) == "specific"
    assert dc.detect_scope(0, 0) == "specific"


# ---------------------------------------------------------------------------
# summarize_window + triage_gsc — position vs impressions vs CTR
# ---------------------------------------------------------------------------
def _rows(days: int, clicks: int, impressions: int, position: float) -> list[dict]:
    return [
        {"clicks": clicks, "impressions": impressions, "gsc_position": position, "tracked_rank": None}
        for _ in range(days)
    ]


def test_summarize_window_weighted_position():
    rows = [
        {"clicks": 1, "impressions": 100, "gsc_position": 5.0, "tracked_rank": None},
        {"clicks": 0, "impressions": 0, "gsc_position": 20.0, "tracked_rank": None},
    ]
    w = dc.summarize_window(rows)
    # 100-impression day dominates the weighted mean
    assert w["position"] < 6.0
    assert w["impressions"] == 100 and w["clicks"] == 1


def test_summarize_window_empty():
    assert dc.summarize_window([]) is None


def test_triage_position_drop_wins():
    prior = dc.summarize_window(_rows(7, 10, 100, 4.0))
    recent = dc.summarize_window(_rows(7, 1, 20, 12.0))
    assert dc.triage_gsc(recent, prior) == "position_drop"


def test_triage_impressions_drop_position_stable():
    prior = dc.summarize_window(_rows(7, 10, 100, 5.0))
    recent = dc.summarize_window(_rows(7, 2, 20, 5.5))
    assert dc.triage_gsc(recent, prior) == "impressions_drop"


def test_triage_ctr_drop_everything_else_stable():
    prior = dc.summarize_window(_rows(7, 20, 100, 5.0))   # CTR 20%
    recent = dc.summarize_window(_rows(7, 10, 100, 5.5))  # CTR 10%, position stable
    assert dc.triage_gsc(recent, prior) == "ctr_drop"


def test_triage_insufficient_data_returns_none():
    prior = dc.summarize_window(_rows(7, 0, 1, 5.0))  # under MIN_PRIOR_IMPRESSIONS
    recent = dc.summarize_window(_rows(7, 0, 1, 9.0))
    assert dc.triage_gsc(recent, prior) is None
    assert dc.triage_gsc(None, prior) is None


# ---------------------------------------------------------------------------
# detect_serp_shift — B2 signals
# ---------------------------------------------------------------------------
def test_serp_shift_aio_appeared():
    shift = dc.detect_serp_shift(
        {"aio_present": True, "query_intent": "commercial"},
        {"aio_present": False, "query_intent": "commercial"},
    )
    assert shift["aio_appeared"] is True and shift["intent_changed"] is False


def test_serp_shift_intent_flip():
    shift = dc.detect_serp_shift(
        {"aio_present": False, "query_intent": "informational"},
        {"aio_present": False, "query_intent": "commercial"},
    )
    assert shift["intent_changed"] is True
    assert shift["intent_from"] == "commercial" and shift["intent_to"] == "informational"


def test_serp_shift_needs_two_snapshots():
    shift = dc.detect_serp_shift({"aio_present": True}, None)
    assert shift == {"aio_appeared": False, "intent_changed": False,
                     "intent_from": None, "intent_to": None}


# ---------------------------------------------------------------------------
# classify_drop — §B precedence
# ---------------------------------------------------------------------------
def test_deindexed_is_b4_regardless():
    r = dc.classify_drop(
        {"alert_type": "deindexed", "keyword": "plumber anaheim"},
        cannibalized={"plumber anaheim"},
        serp_shift={"aio_appeared": True},
        triage="ctr_drop",
    )
    assert r["classification"] == "B4" and r["reason"] == "deindexed_alert"


def test_cannibalization_beats_serp_shift():
    r = dc.classify_drop(
        {"alert_type": "weekly_drop", "keyword": "Plumber Anaheim"},
        cannibalized={"plumber anaheim"},
        serp_shift={"aio_appeared": True},
    )
    assert r["classification"] == "B1"


def test_serp_shift_is_b2():
    r = dc.classify_drop(
        {"alert_type": "weekly_drop", "keyword": "x"},
        serp_shift={"aio_appeared": True, "intent_changed": False},
    )
    assert r["classification"] == "B2"


def test_gsc_triage_maps_to_b3_b4():
    assert dc.classify_drop({"keyword": "x"}, triage="ctr_drop")["classification"] == "B3"
    assert dc.classify_drop({"keyword": "x"}, triage="impressions_drop")["classification"] == "B4"


def test_default_is_b5():
    assert dc.classify_drop({"keyword": "x"})["classification"] == "B5"


def test_playbook_covers_every_classification():
    for c in ("B1", "B2", "B3", "B4", "B5"):
        assert c in dc.RESPONSE_PLAYBOOK
        assert dc.RESPONSE_PLAYBOOK[c]["recommendation"]


# ---------------------------------------------------------------------------
# Planner integration — classified drops render the SOP response
# ---------------------------------------------------------------------------
def test_build_actions_uses_classified_response():
    drops = [
        {
            "keyword": "emergency plumber",
            "alert_type": "weekly_drop",
            "message": "Dropped 4→9.",
            "classification": "B1",
            "response": {
                "label": "Cannibalization",
                "recommendation": "Consolidate per SOP §B1.",
                "cta_label": "GSC Research",
                "cta_path": "clients/c1/gsc-research",
            },
        }
    ]
    actions = build_actions("c1", drops, [], {})
    a = actions[0]
    assert a["classification"] == "B1"
    assert a["diagnosis"].startswith("[B1 — Cannibalization]")
    assert a["recommendation"] == "Consolidate per SOP §B1."
    assert a["cta_path"] == "clients/c1/gsc-research"


def test_build_actions_unclassified_keeps_generic_guidance():
    actions = build_actions(
        "c1", [{"keyword": "x", "alert_type": "weekly_drop", "message": "m"}], [], {}
    )
    assert "Diagnose & reoptimize" in actions[0]["recommendation"]
    assert actions[0]["classification"] is None


def test_sitewide_action_outranks_everything():
    banner = build_sitewide_action("c1", {"open_drops": 6, "tracked_count": 12})
    drop_actions = build_actions(
        "c1", [{"keyword": "x", "alert_type": "deindexed", "message": "m"}], [], {}
    )
    assert banner["sort"] > drop_actions[0]["sort"]
    assert banner["severity"] == "critical"
    assert "§A" in banner["diagnosis"]
