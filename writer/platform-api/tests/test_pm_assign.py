"""Tests for the PACE v1.3 placement engine (§4.6).

Pure `pick_assignee` across the decision axes — skill filter, generalist default,
client eligibility, load ranking, is_primary tie-break, and the overload
hold/least_over fallback — plus the `place_task` already-assigned guard (mocked).
"""

from __future__ import annotations

from services import pm_assign

DEFAULTS = {"default_hours": 1.0, "default_weekly_hours": 30.0}


def _m(gid, cap=30, active=True):
    return {"gid": gid, "name": gid.upper(), "weekly_hours": cap, "active": active}


def _pick(task, members, skills=None, eligible=None, load=None, overload="hold"):
    return pm_assign.pick_assignee(
        task, members, skills or {}, eligible, load or {}, overload=overload, **DEFAULTS
    )


# ---------------------------------------------------------------------------
# Load ranking
# ---------------------------------------------------------------------------
def test_picks_least_loaded():
    r = _pick({}, [_m("a"), _m("b")], load={"a": 20, "b": 5})
    assert r["gid"] == "b" and r["reason"] == "placed"


# ---------------------------------------------------------------------------
# Skill matching
# ---------------------------------------------------------------------------
def test_skill_filter_beats_load():
    # b is less loaded but not skilled in content → a (skilled) still wins.
    skills = {"a": [{"category_key": "content"}], "b": [{"category_key": "link_building"}]}
    r = _pick({"category": "content"}, [_m("a"), _m("b")], skills=skills, load={"a": 20, "b": 0})
    assert r["gid"] == "a"


def test_generalist_is_eligible_for_any_category():
    # a has no skill rows (generalist) → matches content; b skilled elsewhere → excluded.
    skills = {"b": [{"category_key": "link_building"}]}
    r = _pick({"category": "content"}, [_m("a"), _m("b")], skills=skills, load={"a": 10, "b": 0})
    assert r["gid"] == "a"


def test_widen_when_no_skilled_candidate():
    # Nobody is skilled in content (both have other categories) → widen to eligible.
    skills = {"a": [{"category_key": "link_building"}], "b": [{"category_key": "gbp_authority"}]}
    r = _pick({"category": "content"}, [_m("a"), _m("b")], skills=skills, load={"a": 5, "b": 20})
    assert r["gid"] == "a" and r["reason"] == "placed_widened"


def test_is_primary_breaks_ties():
    # Equal remaining; a is primary for content → a.
    skills = {
        "a": [{"category_key": "content", "is_primary": True}],
        "b": [{"category_key": "content", "is_primary": False}],
    }
    r = _pick({"category": "content"}, [_m("a"), _m("b")], skills=skills, load={"a": 10, "b": 10})
    assert r["gid"] == "a"


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------
def test_client_eligibility_restricts_pool():
    r = _pick({}, [_m("a"), _m("b")], eligible=["a"], load={"a": 25, "b": 0})
    assert r["gid"] == "a"  # b is less loaded but not client-eligible


def test_no_eligible_member_holds():
    r = _pick({}, [_m("a"), _m("b")], eligible=["zzz"])
    assert r["gid"] is None and r["held"] and r["reason"] == "no_eligible_member"


def test_inactive_member_excluded():
    r = _pick({}, [_m("a", active=False), _m("b")], load={"a": 0, "b": 25})
    assert r["gid"] == "b"


# ---------------------------------------------------------------------------
# Overload fallback
# ---------------------------------------------------------------------------
def test_overload_hold():
    # Both over capacity (cap 10, load 20) → held.
    r = _pick({}, [_m("a", cap=10), _m("b", cap=10)], load={"a": 20, "b": 20})
    assert r["gid"] is None and r["held"] and r["reason"] == "team_at_capacity"
    assert set(r["candidates"]) == {"a", "b"}


def test_overload_least_over_assigns_anyway():
    # least_over → assign the least-over person (b, remaining -5 vs a's -10).
    r = _pick({}, [_m("a", cap=10), _m("b", cap=10)], load={"a": 20, "b": 15}, overload="least_over")
    assert r["gid"] == "b"


def test_est_hours_respected_in_overload():
    # a has 3h remaining but the task needs 5h → held under "hold".
    r = _pick({"est_hours": 5}, [_m("a", cap=10)], load={"a": 7})
    assert r["held"] and r["reason"] == "team_at_capacity"
    # A 2h task fits.
    r2 = _pick({"est_hours": 2}, [_m("a", cap=10)], load={"a": 7})
    assert r2["gid"] == "a"


# ---------------------------------------------------------------------------
# place_task guard
# ---------------------------------------------------------------------------
def test_place_task_respects_existing_assignment(monkeypatch):
    calls = {"updated": False}
    monkeypatch.setattr(pm_assign, "_get_task",
                        lambda tid: {"id": tid, "client_id": "c1", "assignee_gid": "already"})
    monkeypatch.setattr(pm_assign.task_service, "update_task",
                        lambda *a, **k: calls.update(updated=True))
    r = pm_assign.place_task("t1")
    assert r["reason"] == "already_assigned" and r["gid"] == "already"
    assert calls["updated"] is False  # never overwrote


def test_place_task_missing_task(monkeypatch):
    # _get_task returns None → held task_not_found, never raises.
    monkeypatch.setattr(pm_assign, "_get_task", lambda tid: None)
    r = pm_assign.place_task("gone")
    assert r["held"] and r["reason"] == "task_not_found"
