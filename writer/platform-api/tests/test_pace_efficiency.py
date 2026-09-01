"""Tests for PACE process-efficiency detectors (services/pace_efficiency.py).

Pure detectors only — the impure scan/persist is Supabase I/O. Proves the four
detectors fire on their thresholds, stay quiet below them, key findings stably,
and that collect_findings wires the configured thresholds through.
"""

from __future__ import annotations

from services import pace_efficiency


def _board(clients=None, overloaded=None):
    return {"clients": clients or [], "workload": {"overloaded": overloaded or []}}


def _client(cid, overdue=0, behind=False, unacted=None):
    return {
        "client_id": cid,
        "counts": {"overdue": overdue},
        "month_pace": {"behind": behind},
        "unacted_producer": unacted or [],
    }


# --- slip / bottleneck ------------------------------------------------------
def test_slip_fires_on_overdue_run():
    board = _board(clients=[_client("c1", overdue=4)])
    out = pace_efficiency.detect_slip_bottleneck(board, slip_min=3, names={"c1": "Acme"})
    keys = {f["finding_key"] for f in out}
    assert "slip:client:c1" in keys
    slip = next(f for f in out if f["finding_key"] == "slip:client:c1")
    assert slip["client_id"] == "c1" and slip["category"] == "slip_bottleneck"
    assert "Acme" in slip["title"]


def test_slip_quiet_below_threshold_unless_behind():
    # 2 overdue, not behind, min 3 → nothing.
    assert pace_efficiency.detect_slip_bottleneck(
        _board(clients=[_client("c1", overdue=2)]), slip_min=3) == []
    # 2 overdue AND behind pace → the softened bar (slip_min-1) fires.
    out = pace_efficiency.detect_slip_bottleneck(
        _board(clients=[_client("c1", overdue=2, behind=True)]), slip_min=3)
    assert out and out[0]["finding_key"] == "slip:client:c1"


def test_bottleneck_member_from_workload():
    board = _board(overloaded=[{"gid": "m1", "name": "Ivy", "open_hours": 90,
                                "open_count": 30, "flags": ["90h open"]}])
    out = pace_efficiency.detect_slip_bottleneck(board, slip_min=3)
    assert out[0]["finding_key"] == "bottleneck:member:m1"
    assert out[0]["client_id"] is None and out[0]["member_gid"] == "m1"


# --- rework -----------------------------------------------------------------
def test_rework_qa_and_reopen():
    qa = {("c1", "website_page"): 4, ("c2", "gbp_posts"): 1}
    reopen = {"c1": 5, "c2": 1}
    out = pace_efficiency.detect_rework(qa, reopen, rework_min=3, names={"c1": "Acme"})
    keys = {f["finding_key"] for f in out}
    assert "rework:qa:c1:website_page" in keys   # 4 >= 3
    assert "rework:reopen:c1" in keys            # 5 >= 3
    assert "rework:qa:c2:gbp_posts" not in keys  # 1 < 3
    assert "rework:reopen:c2" not in keys


# --- cadence ----------------------------------------------------------------
def test_cadence_fires_when_many_behind():
    board = _board(clients=[_client(f"c{i}", behind=True) for i in range(3)])
    out = pace_efficiency.detect_cadence(board, cadence_min_clients=3)
    assert len(out) == 1 and out[0]["finding_key"] == "cadence:month_pace"
    assert out[0]["evidence"]["behind_clients"] == 3


def test_cadence_quiet_below_threshold():
    board = _board(clients=[_client("c1", behind=True), _client("c2", behind=True)])
    assert pace_efficiency.detect_cadence(board, cadence_min_clients=3) == []


# --- producer noise ---------------------------------------------------------
def test_producer_noise_rolls_up_by_source():
    board = _board(clients=[
        _client("c1", unacted=[{"source": "rank_drop"}, {"source": "rank_drop"}, {"source": "rank_drop"}]),
        _client("c2", unacted=[{"source": "rank_drop"}, {"source": "action_plan"}]),
    ])
    out = pace_efficiency.detect_producer_noise(board, producer_min=4)
    keys = {f["finding_key"] for f in out}
    assert "producer_noise:rank_drop" in keys      # 4 across clients >= 4
    assert "producer_noise:action_plan" not in keys  # 1 < 4


# --- collect_findings wires configured thresholds ---------------------------
def test_collect_findings_uses_settings(monkeypatch):
    monkeypatch.setattr(pace_efficiency.settings, "pace_efficiency_slip_min", 3)
    monkeypatch.setattr(pace_efficiency.settings, "pace_efficiency_rework_min", 3)
    monkeypatch.setattr(pace_efficiency.settings, "pace_efficiency_cadence_min_clients", 3)
    monkeypatch.setattr(pace_efficiency.settings, "pace_efficiency_producer_min", 5)
    board = _board(clients=[_client("c1", overdue=5)])
    out = pace_efficiency.collect_findings(board, {("c1", "website_page"): 4}, {})
    keys = {f["finding_key"] for f in out}
    assert "slip:client:c1" in keys and "rework:qa:c1:website_page" in keys
