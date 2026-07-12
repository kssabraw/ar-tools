"""Tests for PACE v1.4 slip forecasting (§4.12) — the pure model."""

from __future__ import annotations

from datetime import date

from services import pace_slips as S

MODEL = {"default_hours": 1.0, "default_weekly_hours": 30.0, "daily_workdays": 5.0}
TODAY = date(2026, 7, 13)  # a Monday
INITIAL = {"not_started"}


def _member(gid, cap=30):
    return {"gid": gid, "name": gid.upper(), "weekly_hours": cap}


def _task(tid, name, due, est=2, gid="ivy", status="not_started"):
    return {"id": tid, "name": name, "due_date": due, "est_hours": est,
            "assignee_gid": gid, "client_id": "c1", "status_key": status}


def _forecast(tasks, members=None, horizon=5):
    members = members or {"ivy": _member("ivy")}
    return S.forecast_slips(tasks, members, INITIAL, TODAY, horizon, **MODEL)


# ---------------------------------------------------------------------------
# forecast_slips
# ---------------------------------------------------------------------------
def test_overbooked_assignee_slips():
    # Ivy: 30h/wk → 6h/day; due Wednesday = 2 business days = 12h window.
    # This 8h task + another 6h due Tuesday = 14h needed > 12h → slips.
    tasks = [
        _task("t1", "Big page", "2026-07-15", est=8),
        _task("t2", "Other work", "2026-07-14", est=6),
    ]
    slips = _forecast(tasks)
    assert [s["task"]["id"] for s in slips] == ["t1"]
    s = slips[0]
    assert s["reason"] == "no_capacity" and s["needed"] == 8 and s["available"] == 6.0


def test_free_assignee_does_not_slip():
    slips = _forecast([_task("t1", "Small", "2026-07-15", est=4)])
    assert slips == []


def test_started_task_presumed_on_track():
    tasks = [_task("t1", "In flight", "2026-07-14", est=40, status="in_progress")]
    assert _forecast(tasks) == []


def test_unassigned_due_soon_slips():
    slips = _forecast([_task("t1", "Orphan", "2026-07-15", est=2, gid=None)])
    assert slips[0]["reason"] == "unassigned"


def test_outside_horizon_ignored():
    assert _forecast([_task("t1", "Far away", "2026-07-30", est=99)], horizon=5) == []
    # Due today (not strictly future) is the overdue signal's job, not a forecast.
    assert _forecast([_task("t1", "Today", "2026-07-13", est=99)]) == []


def test_untracked_assignee_stays_silent():
    tasks = [_task("t1", "Ghost's task", "2026-07-15", est=99, gid="ghost")]
    assert _forecast(tasks, members={"ivy": _member("ivy")}) == []


# ---------------------------------------------------------------------------
# next_feasible_due
# ---------------------------------------------------------------------------
def test_next_feasible_due_pushes_business_days():
    # Deficit 8h at 6h/day → 2 extra business days; Wed + 2bd = Friday.
    slip = {"due": date(2026, 7, 15), "needed": 20.0, "available": 12.0}
    assert S.next_feasible_due(slip, _member("ivy"), TODAY, default_weekly_hours=30,
                               daily_workdays=5) == date(2026, 7, 17)
    # Friday due + 1bd crosses the weekend → Monday.
    slip2 = {"due": date(2026, 7, 17), "needed": 13.0, "available": 12.0}
    assert S.next_feasible_due(slip2, _member("ivy"), TODAY, default_weekly_hours=30,
                               daily_workdays=5) == date(2026, 7, 20)


def test_next_feasible_due_gives_up_past_cap():
    slip = {"due": date(2026, 7, 15), "needed": 500.0, "available": 0.0}
    assert S.next_feasible_due(slip, _member("ivy"), TODAY, default_weekly_hours=30,
                               daily_workdays=5) is None
