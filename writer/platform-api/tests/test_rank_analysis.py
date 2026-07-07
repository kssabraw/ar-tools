"""Unit tests for the Organic Rank Analysis pure helpers (no network)."""

from __future__ import annotations

from services import rank_analysis as ra


# ---------------------------------------------------------------------------
# trajectory_verdict
# ---------------------------------------------------------------------------
def test_trajectory_verdict_velocity_labels():
    summary = {"primary_source": "gsc", "avg_7": 8.0, "avg_30": 10.0, "avg_90": 12.0,
               "clicks_30d": 40, "impressions_30d": 900, "ctr_30d": 0.044, "sparkline": [12, 10, 8]}
    fc = {"current_position": 8.0, "trend_per_week": -2.5,
          "projected_position_30d": 4.0, "projected_position_90d": 2.0, "confidence": "high"}
    v = ra.trajectory_verdict(summary, fc, "climbing")
    assert v["velocity"] == "improving_fast"
    assert v["status"] == "climbing"
    assert v["current_position"] == 8.0

    v2 = ra.trajectory_verdict(summary, {**fc, "trend_per_week": 3.0}, "dropping")
    assert v2["velocity"] == "declining_fast"

    v3 = ra.trajectory_verdict(summary, {**fc, "trend_per_week": 0.0}, "stable")
    assert v3["velocity"] == "holding"

    v4 = ra.trajectory_verdict(summary, {**fc, "trend_per_week": None}, "no_data")
    assert v4["velocity"] == "flat"


# ---------------------------------------------------------------------------
# _classify_advantage / build_competitor_breakdown
# ---------------------------------------------------------------------------
def test_classify_advantage_authority_needs_both_bars():
    # Clear absolute + relative lead → authority.
    assert ra._classify_advantage(60, False, None, 20, False, None) == "authority"
    # Big relative multiple but tiny absolute lead → not authority.
    assert ra._classify_advantage(6, False, None, 2, False, None) != "authority"
    # Absolute lead but under the 1.5x bar → not authority.
    assert ra._classify_advantage(30, False, None, 25, False, None) != "authority"


def test_classify_advantage_targeting_and_topical():
    assert ra._classify_advantage(5, True, None, 5, False, None) == "targeting"
    assert ra._classify_advantage(5, False, "specialist", 5, True, "generalist") == "topical"
    assert ra._classify_advantage(5, False, None, 5, True, None) == "established"


def test_competitor_breakdown_only_above_client():
    top = [
        {"position": 1, "domain": "a.com", "url": "a", "is_client": False,
         "targeted": True, "topical_focus": "specialist", "url_rating": 300, "referring_domains": 80},
        {"position": 2, "domain": "b.com", "url": "b", "is_client": False,
         "targeted": False, "topical_focus": "generalist", "url_rating": 100, "referring_domains": 10},
        {"position": 3, "domain": "client.com", "url": "c", "is_client": True,
         "targeted": True, "topical_focus": "specialist", "url_rating": 120, "referring_domains": 12},
    ]
    out = ra.build_competitor_breakdown(
        3, top, {"a.com": 200, "b.com": 90}, {"rd": 12, "ur": 120, "dr": 90, "targeted": True, "topical_focus": "specialist"},
    )
    assert [c["position"] for c in out] == [1, 2]  # only positions above the client's #3
    assert out[0]["primary_reason"] == "authority"  # 80 RD vs client 12
    assert out[0]["rd_gap"] == 68


def test_competitor_breakdown_client_absent_all_above():
    top = [
        {"position": 1, "domain": "a.com", "url": "a", "is_client": False,
         "targeted": True, "topical_focus": None, "url_rating": 300, "referring_domains": 80},
    ]
    out = ra.build_competitor_breakdown(
        None, top, {"a.com": 200}, {"rd": None, "ur": None, "dr": None, "targeted": False, "topical_focus": None},
    )
    assert len(out) == 1  # client not in top-10 → every competitor is "above"


# ---------------------------------------------------------------------------
# authority_gap
# ---------------------------------------------------------------------------
def test_authority_gap_rd_to_match():
    comps = [
        {"referring_domains": 40, "url_rating": 200, "domain_rating": 150},
        {"referring_domains": 60, "url_rating": 300, "domain_rating": 250},
        {"referring_domains": 20, "url_rating": 100, "domain_rating": 100},
    ]
    gap = ra.authority_gap({"rd": 10, "ur": 120, "dr": 80}, comps)
    assert gap["median_competitor_rd"] == 40
    assert gap["rd_to_match"] == 30  # 40 median − 10 client
    assert gap["dr_deficit"] == 70   # 150 median − 80


def test_authority_gap_client_ahead_is_zero_floor():
    comps = [{"referring_domains": 5, "url_rating": 50, "domain_rating": 40}]
    gap = ra.authority_gap({"rd": 100, "ur": 400, "dr": 300}, comps)
    assert gap["rd_to_match"] == 0  # client already out-links → floored at 0


def test_authority_gap_no_competitor_data():
    gap = ra.authority_gap({"rd": 10, "ur": 100, "dr": 80}, [])
    assert gap["median_competitor_rd"] is None
    assert gap["rd_to_match"] is None


# ---------------------------------------------------------------------------
# urgency_key / compute_priority
# ---------------------------------------------------------------------------
def test_urgency_key_precedence():
    assert ra.urgency_key("stable", True, 5) == "alert"        # alert wins
    assert ra.urgency_key("dropping", False, 5) == "dropping"
    assert ra.urgency_key("stable", False, 2) == "won"         # top-3 stable
    assert ra.urgency_key("stable", False, 8) == "striking"    # striking band
    assert ra.urgency_key("climbing", False, 40) == "climbing"
    assert ra.urgency_key("stable", False, 40) == "stable"


def test_compute_priority_scales_by_urgency():
    base = ra.compute_priority(80, 1000.0, "stable")
    alert = ra.compute_priority(80, 1000.0, "alert")
    won = ra.compute_priority(80, 1000.0, "won")
    assert base == 800.0            # 0.8 × 1000 × 1.0
    assert alert == 1200.0          # × 1.5
    assert won == 400.0             # × 0.5
    assert ra.compute_priority(None, 1000.0, "stable") is None
    assert ra.compute_priority(80, None, "stable") is None


# ---------------------------------------------------------------------------
# build_work_order
# ---------------------------------------------------------------------------
def _traj(pos):
    return {"current_position": pos}


def test_work_order_authority_gap_leverage_higher_when_close():
    gap = {"rd_to_match": 30, "median_competitor_rd": 40, "client_rd": 10}
    near = ra.build_work_order(_traj(8), gap, [], {}, False, [], 8, 1, None)
    far = ra.build_work_order(_traj(45), gap, [], {}, False, [], 45, 1, None)
    a_near = next(i for i in near if i["type"] == "authority")
    a_far = next(i for i in far if i["type"] == "authority")
    assert a_near["leverage"] > a_far["leverage"]  # striking distance → more leverage


def test_work_order_client_absent_adds_create_page():
    order = ra.build_work_order(_traj(None), {}, [], {}, False, [], None, 0, None)
    assert any(i["type"] == "targeting" and i["cta"] == "create_page" for i in order)


def test_work_order_cannibalization_from_multiple_pages():
    order = ra.build_work_order(_traj(6), {}, [], {}, False, [], 6, 3, None)
    assert any(i["type"] == "cannibalization" for i in order)


def test_work_order_aio_and_sorted_by_leverage():
    gap = {"rd_to_match": 5, "median_competitor_rd": 10, "client_rd": 5}
    order = ra.build_work_order(
        _traj(6), gap, [], {}, True, [{"domain": "wikipedia.org"}], 6, 1, None,
    )
    assert any(i["type"] == "aio" for i in order)
    leverages = [i["leverage"] for i in order]
    assert leverages == sorted(leverages, reverse=True)


def test_work_order_topical_opening():
    comps = [{"primary_reason": "topical", "topical_focus": "generalist"}]
    order = ra.build_work_order(
        _traj(6), {}, comps, {"client_topical_focus": "specialist"}, False, [], 6, 1, None,
    )
    assert any(i["type"] == "topical_opening" for i in order)
