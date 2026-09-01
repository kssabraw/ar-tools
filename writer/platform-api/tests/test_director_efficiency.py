"""Tests for DORA's process-efficiency synthesis (services/director/efficiency.py).

Pure only: the read-model → observations synthesis (findings + coordination +
friction seams + no-effect effort), severity ranking, the alertable subset, and
the deterministic report body. The LLM narrative + emits are best-effort I/O.
"""

from __future__ import annotations

from services.director import efficiency


def _model():
    return {
        "pace_efficiency": {"findings": [
            {"finding_key": "slip:client:c1", "category": "slip_bottleneck",
             "severity": "warning", "title": "Delivery slipping for Acme",
             "recommendation": "Rebalance the overdue work."},
            {"finding_key": "producer_noise:rank_drop", "category": "producer_noise",
             "severity": "info", "title": "rank_drop producer noisy",
             "recommendation": "Tune thresholds."},
        ]},
        "coordination": {
            "open_blockers": [{"ref": "placement:t1", "subject": "Can't staff X"}],
            "stalled": [{"kind": "handoff", "age_hours": 72}],
            "loops": [{"correlation_id": "z", "flips": 2}],
        },
        "flow": {"flags": [
            {"seam": "strategist_approved_unplaced", "client_id": "c1"},
            {"seam": "duplicate_target", "client_id": "c2"},
        ]},
        "interventions": {"by_verdict": {"no_effect": 4, "worked": 2}},
    }


def test_build_view_collects_all_sources():
    view = efficiency.build_efficiency_view(_model())
    keys = {o["key"] for o in view["observations"]}
    assert "finding:slip:client:c1" in keys
    assert "finding:producer_noise:rank_drop" in keys
    assert "coordination:blocker:placement:t1" in keys
    assert "coordination:stalled" in keys
    assert "coordination:loops" in keys
    assert "seam:strategist_approved_unplaced" in keys
    assert "seam:duplicate_target" in keys
    assert "effort:no_effect" in keys


def test_build_view_sorts_warnings_before_info():
    view = efficiency.build_efficiency_view(_model())
    sevs = [o["severity"] for o in view["observations"]]
    # No 'info' appears before a 'warning'.
    first_info = next((i for i, s in enumerate(sevs) if s == "info"), len(sevs))
    assert all(s == "warning" or s == "critical" for s in sevs[:first_info])
    assert view["counts"]["observations"] == len(view["observations"])


def test_significant_is_warning_plus_only():
    view = efficiency.build_efficiency_view(_model())
    sig_keys = {o["key"] for o in efficiency.significant(view)}
    # Warnings in.
    assert "finding:slip:client:c1" in sig_keys
    assert "coordination:blocker:placement:t1" in sig_keys
    assert "coordination:stalled" in sig_keys
    assert "seam:strategist_approved_unplaced" in sig_keys
    # Info out.
    assert "finding:producer_noise:rank_drop" not in sig_keys
    assert "coordination:loops" not in sig_keys
    assert "seam:duplicate_target" not in sig_keys
    assert "effort:no_effect" not in sig_keys


def test_report_body_and_empty():
    view = efficiency.build_efficiency_view(_model())
    body = efficiency.build_report_body(view)
    assert "Process efficiency" in body and "Delivery slipping for Acme" in body
    assert efficiency.build_report_body({"observations": []}) == ""


def test_alertable_caps_and_keeps_worst():
    # 20 warning findings → alertable caps to the requested top N, severity-ranked.
    findings = [{"finding_key": f"slip:client:c{i}", "category": "slip_bottleneck",
                 "severity": "warning", "title": f"slip {i}", "recommendation": "x"}
                for i in range(20)]
    view = efficiency.build_efficiency_view({"pace_efficiency": {"findings": findings}})
    assert len(efficiency.significant(view)) == 20
    capped = efficiency.alertable(view, cap=15)
    assert len(capped) == 15
    assert all(o["severity"] in ("warning", "critical") for o in capped)
    # cap 0/None → uncapped.
    assert len(efficiency.alertable(view, cap=0)) == 20


def test_no_effect_below_floor_not_flagged():
    m = _model()
    m["interventions"] = {"by_verdict": {"no_effect": 2}}  # < 3 floor
    keys = {o["key"] for o in efficiency.build_efficiency_view(m)["observations"]}
    assert "effort:no_effect" not in keys
