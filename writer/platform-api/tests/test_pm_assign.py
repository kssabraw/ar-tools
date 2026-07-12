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


def test_overload_unknown_value_fails_closed():
    # A config typo ("holdd") must behave as hold, never silently over-assign.
    r = _pick({}, [_m("a", cap=10)], load={"a": 20}, overload="holdd")
    assert r["gid"] is None and r["held"] and r["reason"] == "team_at_capacity"


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


# ---------------------------------------------------------------------------
# build_rebalance (§4.11) — pure move planning
# ---------------------------------------------------------------------------
def _task(tid, name, est, client="c1", category=None):
    return {"id": tid, "name": name, "est_hours": est, "client_id": client, "category": category}


def test_rebalance_smallest_first_until_under():
    # Ivy is 5h over; movable 2h + 4h + 6h → 2h then 4h (6 freed ≥ 5), 6h stays.
    plan = pm_assign.build_rebalance(
        "ivy", 5.0,
        [_task("t3", "big", 6), _task("t1", "small", 2), _task("t2", "mid", 4)],
        [_m("ivy"), _m("bo", cap=30)], {}, {}, {"ivy": 35, "bo": 5}, **DEFAULTS,
    )
    assert [m["task_id"] for m in plan["moves"]] == ["t1", "t2"]
    assert plan["freed"] == 6.0 and plan["remaining_over"] == 0.0
    assert all(m["to_gid"] == "bo" for m in plan["moves"])


def test_rebalance_never_targets_the_overloaded_member():
    plan = pm_assign.build_rebalance(
        "ivy", 3.0, [_task("t1", "x", 2)], [_m("ivy")], {}, {}, {"ivy": 35}, **DEFAULTS,
    )
    assert plan["moves"] == [] and plan["remaining_over"] == 3.0


def test_rebalance_simulated_load_prevents_tipping_targets():
    # Bo has 2h headroom: absorbs the 2h task; the next 2h would tip him → skipped.
    plan = pm_assign.build_rebalance(
        "ivy", 10.0, [_task("t1", "a", 2), _task("t2", "b", 2)],
        [_m("ivy"), _m("bo", cap=10)], {}, {}, {"ivy": 40, "bo": 8}, **DEFAULTS,
    )
    assert len(plan["moves"]) == 1 and plan["moves"][0]["task_id"] == "t1"
    assert plan["remaining_over"] == 8.0  # honest partial relief


def test_rebalance_respects_skills_and_eligibility():
    skills = {"bo": [{"category_key": "link_building"}], "cat": []}  # cat = generalist
    plan = pm_assign.build_rebalance(
        "ivy", 4.0, [_task("t1", "content piece", 3, category="content")],
        [_m("ivy"), _m("bo"), _m("cat")], skills,
        {"c1": ["ivy", "bo", "cat"]}, {"ivy": 35, "bo": 0, "cat": 10}, **DEFAULTS,
    )
    # Bo is least-loaded but skilled elsewhere → the generalist cat takes it.
    assert plan["moves"][0]["to_gid"] == "cat"


# ---------------------------------------------------------------------------
# replace_member_skills — validate BEFORE the destructive delete
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, sb, table):
        self._sb, self._table, self._op = sb, table, "select"

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def delete(self, *a, **k):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op = "insert"
        return self

    def execute(self):
        self._sb.calls.append((self._op, self._table))
        data = self._sb.data.get(self._table, []) if self._op == "select" else []
        return type("R", (), {"data": data})()


class _FakeSB:
    def __init__(self, data):
        self.data, self.calls = data, []

    def table(self, name):
        return _FakeQuery(self, name)


def test_replace_skills_rejects_unknown_category_before_delete(monkeypatch):
    sb = _FakeSB({"asana_team_members": [{"gid": "g1"}], "task_categories": [{"key": "content"}]})
    monkeypatch.setattr(pm_assign, "get_supabase", lambda: sb)
    import pytest
    with pytest.raises(ValueError, match="unknown_category_key"):
        pm_assign.replace_member_skills("g1", [{"category_key": "bogus"}])
    # The critical property: NO delete ran — the member's skills are intact.
    assert ("delete", "task_member_skills") not in sb.calls


def test_replace_skills_rejects_unknown_member(monkeypatch):
    sb = _FakeSB({"asana_team_members": [], "task_categories": [{"key": "content"}]})
    monkeypatch.setattr(pm_assign, "get_supabase", lambda: sb)
    import pytest
    with pytest.raises(ValueError, match="unknown_member"):
        pm_assign.replace_member_skills("ghost", [{"category_key": "content"}])
    assert ("delete", "task_member_skills") not in sb.calls


def test_replace_skills_happy_path_deletes_then_inserts(monkeypatch):
    sb = _FakeSB({"asana_team_members": [{"gid": "g1"}], "task_categories": [{"key": "content"}]})
    monkeypatch.setattr(pm_assign, "get_supabase", lambda: sb)
    saved = pm_assign.replace_member_skills("g1", [{"category_key": "content", "is_primary": True}])
    assert saved == [{"category_key": "content", "is_primary": True}]
    ops = [c for c in sb.calls if c[1] == "task_member_skills"]
    assert ops == [("delete", "task_member_skills"), ("insert", "task_member_skills")]
