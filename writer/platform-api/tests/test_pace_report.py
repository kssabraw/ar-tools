"""Tests for the PACE v1.3 delivery report (§4.7).

Pure aggregations (throughput grouping, utilization math, portfolio summarize)
and the deterministic text render + the weekly-digest gating.
"""

from __future__ import annotations

from datetime import date

from services import pace_report


def test_throughput_by_category():
    rows = [
        {"category": "content"}, {"category": "content"},
        {"category": "link_building"}, {"category": None}, {"category": ""},
    ]
    out = pace_report.throughput(rows, by="category")
    assert out["content"] == 2 and out["link_building"] == 1 and out["Uncategorized"] == 2
    # Sorted most-first.
    assert list(out)[0] in ("content", "Uncategorized")


def test_throughput_by_person_fallback():
    rows = [{"assignee_name": "Ivy"}, {"assignee_name": None}, {"assignee_name": "Ivy"}]
    out = pace_report.throughput(rows, by="assignee_name")
    assert out == {"Ivy": 2, "Unassigned": 1}


def test_utilization_math_and_sort():
    members = [
        {"name": "A", "open_hours": 10, "weekly_hours": 20, "overloaded": False},
        {"name": "B", "open_hours": 30, "weekly_hours": 20, "overloaded": True},
        {"name": "C", "open_hours": 5, "weekly_hours": 0, "overloaded": False},  # no cap
    ]
    util = pace_report.utilization(members)
    by_name = {u["name"]: u for u in util}
    assert by_name["A"]["pct"] == 50
    assert by_name["B"]["pct"] == 150 and by_name["B"]["over"] is True
    assert by_name["C"]["pct"] is None  # zero capacity → undefined, not a crash
    # Most-loaded first (B 150% before A 50%).
    assert util[0]["name"] == "B"


def test_summarize_rolls_envelopes():
    clients = [
        {"stale": [1, 2], "overdue": [1], "unassigned": [], "unacted_producer": [1],
         "month_pace": {"behind": True}},
        {"stale": [], "overdue": [1, 2], "unassigned": [1], "unacted_producer": [],
         "month_pace": {"behind": False}},
    ]
    s = pace_report.summarize(clients)
    assert s == {"stuck": 2, "overdue": 3, "unassigned": 1, "unacted": 1, "behind_pace": 1}


def test_render_text_is_readable():
    report = {
        "scope": "portfolio", "as_of": "2026-07-12", "period_days": 7,
        "clients_covered": 3, "completed_count": 9,
        "throughput_by_category": {"content": 5, "link_building": 4},
        "throughput_by_person": {"Ivy": 6, "Minda": 3},
        "overdue": 2, "stuck": 1, "unassigned": 0, "unacted": 1, "behind_pace": 1,
        "utilization": [{"name": "Ivy", "pct": 130, "over": True},
                        {"name": "Minda", "pct": 60, "over": False}],
    }
    text = pace_report.render_text(report)
    assert "Delivery report — all clients" in text
    assert "Completed: *9*" in text
    assert "2 overdue" in text
    assert "Ivy (130%)" in text  # over-capacity callout


def test_weekly_emit_gated(monkeypatch):
    # Disabled → no emit.
    monkeypatch.setattr(pace_report.settings, "pace_enabled", False)
    assert pace_report.maybe_emit_weekly(date(2026, 7, 13))["emitted"] is False
    # Enabled but wrong weekday → not due.
    monkeypatch.setattr(pace_report.settings, "pace_enabled", True)
    monkeypatch.setattr(pace_report.settings, "pace_report_weekday", 0)  # Monday
    assert pace_report.maybe_emit_weekly(date(2026, 7, 14))["reason"] == "not_due"  # a Tuesday
    # None weekday → off even when enabled.
    monkeypatch.setattr(pace_report.settings, "pace_report_weekday", None)
    assert pace_report.maybe_emit_weekly(date(2026, 7, 13))["reason"] == "not_due"


def test_weekly_emit_fires_on_configured_day(monkeypatch):
    monkeypatch.setattr(pace_report.settings, "pace_enabled", True)
    monkeypatch.setattr(pace_report.settings, "pace_report_weekday", 0)  # Monday
    monkeypatch.setattr(pace_report, "build_report", lambda cid, today=None: {
        "completed_count": 4, "overdue": 1, "scope": "portfolio", "period_days": 7, "as_of": "x"})
    captured = {}
    monkeypatch.setattr(pace_report.notifications, "emit",
                        lambda **kw: captured.update(kw))
    r = pace_report.maybe_emit_weekly(date(2026, 7, 13))  # 2026-07-13 is a Monday
    assert r["emitted"] is True
    assert captured["kind"] == "pace_report" and captured["dedupe_key"].startswith("pace_report:")
