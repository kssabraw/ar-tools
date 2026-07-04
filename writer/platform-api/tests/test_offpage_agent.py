"""Unit tests for services.offpage_agent — pure RD-change detection + episode
resolution + the planner's §A.5 actions. No network / no DB.
"""

from __future__ import annotations

from services import offpage_agent as oa
from services.reopt_planner import build_actions, build_offpage_actions


# ---------------------------------------------------------------------------
# detect_rd_change — both bars (relative + absolute) must clear
# ---------------------------------------------------------------------------
def test_rd_loss_detected():
    c = oa.detect_rd_change(100, 80)  # −20%, −20 domains
    assert c["type"] == "rd_loss" and c["delta_pct"] == -20.0


def test_rd_spike_detected():
    c = oa.detect_rd_change(100, 200)  # +100%, +100 domains
    assert c["type"] == "rd_spike" and c["delta_pct"] == 100.0


def test_small_profile_loss_needs_absolute_bar():
    # −40% but only −2 domains → noise, not an alert
    assert oa.detect_rd_change(5, 3) is None


def test_large_profile_jitter_needs_relative_bar():
    # −11 domains but only −1.1% → noise
    assert oa.detect_rd_change(1000, 989) is None


def test_missing_data_is_never_an_alert():
    assert oa.detect_rd_change(None, 80) is None
    assert oa.detect_rd_change(100, None) is None
    assert oa.detect_rd_change(0, 50) is None


# ---------------------------------------------------------------------------
# should_resolve — the episode's clearing condition
# ---------------------------------------------------------------------------
def test_loss_resolves_on_recovery():
    a = {"alert_type": "rd_loss", "from_rd": 100}
    assert oa.should_resolve(a, 96) is True   # ≥95% of pre-loss
    assert oa.should_resolve(a, 80) is False


def test_spike_resolves_when_settled():
    a = {"alert_type": "rd_spike", "from_rd": 100}
    assert oa.should_resolve(a, 110) is True  # ≤120% of pre-spike
    assert oa.should_resolve(a, 200) is False


def test_resolve_needs_current_read():
    assert oa.should_resolve({"alert_type": "rd_loss", "from_rd": 100}, None) is False


# ---------------------------------------------------------------------------
# Planner §A.5 actions
# ---------------------------------------------------------------------------
def test_offpage_actions_render_sop_responses():
    alerts = [
        {"alert_type": "rd_loss", "message": "RD fell 20%.", "delta_pct": -20},
        {"alert_type": "rd_spike", "message": "RD jumped 100%.", "delta_pct": 100},
    ]
    actions = build_offpage_actions("c1", alerts)
    loss = next(a for a in actions if a["kind"] == "rd_loss")
    spike = next(a for a in actions if a["kind"] == "rd_spike")
    assert "Recipe Engine" in loss["recommendation"]
    assert "never disavow" in spike["recommendation"]
    assert loss["sort"] > spike["sort"]  # loss outranks spike within the tier


def test_offpage_sits_between_drops_and_cannibalization():
    drop = build_actions(
        "c1", [{"keyword": "x", "alert_type": "weekly_drop", "message": "m"}], [], {}
    )[0]
    cannibal = build_actions(
        "c1", [], [], {"cannibalization": [{"query": "q", "page_count": 2, "total_impressions": 10}]}
    )[0]
    loss = build_offpage_actions("c1", [{"alert_type": "rd_loss", "message": "m", "delta_pct": -20}])[0]
    assert drop["sort"] > loss["sort"] > cannibal["sort"]
