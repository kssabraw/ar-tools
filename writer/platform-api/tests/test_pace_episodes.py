"""Tests for the PACE v1.4 follow-through episodes (§4.9).

Pure helpers (business-day math, signal flattening, escalation/renudge gating)
plus the chase generator's proposal shapes with the DB layer monkeypatched.
"""

from __future__ import annotations

from datetime import date

from config import settings
from services import pace_episodes as E


# ---------------------------------------------------------------------------
# business_days_between
# ---------------------------------------------------------------------------
def test_business_days_between():
    mon, thu = date(2026, 7, 13), date(2026, 7, 16)
    assert E.business_days_between(mon, thu) == 3          # Tue, Wed, Thu
    fri, next_mon = date(2026, 7, 17), date(2026, 7, 20)
    assert E.business_days_between(fri, next_mon) == 1     # weekend skipped
    assert E.business_days_between(mon, mon) == 0
    assert E.business_days_between(thu, mon) == 0          # inverted → 0


# ---------------------------------------------------------------------------
# signal_keys
# ---------------------------------------------------------------------------
def test_signal_keys_flattens_all_kinds():
    clients = [{
        "client_id": "c1",
        "stale": [{"id": "t1", "name": "A", "assignee_name": "Ivy", "status_key": "in_review"}],
        "overdue": [{"id": "t2", "name": "B", "assignee_name": "Bo"}],
        "unassigned": [{"id": "t3", "name": "C"}],
        "unacted_producer": [{"id": "t4", "name": "D", "source": "rank_drop"}],
    }]
    keys = E.signal_keys(clients)
    assert set(keys) == {("t1", "stale"), ("t2", "overdue"), ("t3", "unassigned"), ("t4", "unacted")}
    assert keys[("t1", "stale")]["client_id"] == "c1"


# ---------------------------------------------------------------------------
# should_escalate — the single public escalation
# ---------------------------------------------------------------------------
def _ep(opened="2026-07-13T08:00:00+00:00", moved=None, escalated=None, status="open"):
    return {"opened_at": opened, "last_movement_at": moved,
            "escalated_at": escalated, "status": status}


def test_escalates_after_threshold_without_movement():
    # Opened Monday; Thursday = 3 business days → escalate.
    assert E.should_escalate(_ep(), date(2026, 7, 16), 3) is True
    # Wednesday = 2 → not yet.
    assert E.should_escalate(_ep(), date(2026, 7, 15), 3) is False


def test_movement_resets_the_clock():
    # Opened Monday, moved Wednesday → Thursday is only 1 business day since movement.
    ep = _ep(moved="2026-07-15T10:00:00+00:00")
    assert E.should_escalate(ep, date(2026, 7, 16), 3) is False
    # The following Monday: Thu+Fri+Mon = 3 since Wednesday → escalate.
    assert E.should_escalate(ep, date(2026, 7, 20), 3) is True


def test_never_escalates_twice_or_when_closed():
    assert E.should_escalate(_ep(escalated="2026-07-16T08:00:00+00:00"), date(2026, 7, 30), 3) is False
    assert E.should_escalate(_ep(status="resolved"), date(2026, 7, 30), 3) is False


def test_weekend_does_not_count():
    # Opened Friday; Monday = 1 business day, Wednesday = 3.
    ep = _ep(opened="2026-07-17T08:00:00+00:00")
    assert E.should_escalate(ep, date(2026, 7, 20), 3) is False
    assert E.should_escalate(ep, date(2026, 7, 22), 3) is True


# ---------------------------------------------------------------------------
# due_for_proposal — aggressive renudge pacing
# ---------------------------------------------------------------------------
def test_due_for_proposal():
    today = date(2026, 7, 16)
    assert E.due_for_proposal({"last_proposed_at": None}, today, 1) is True
    assert E.due_for_proposal({"last_proposed_at": "2026-07-15T08:00:00+00:00"}, today, 1) is True
    assert E.due_for_proposal({"last_proposed_at": "2026-07-16T06:00:00+00:00"}, today, 1) is False
    # renudge_days=2: yesterday's proposal isn't due again yet.
    assert E.due_for_proposal({"last_proposed_at": "2026-07-15T08:00:00+00:00"}, today, 2) is False


# ---------------------------------------------------------------------------
# The chase generator — proposal shapes
# ---------------------------------------------------------------------------
def test_generator_shapes(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    eps = [
        {  # assigned + stale → hygiene-worded nudge
            "id": "e1", "kind": "stale", "status": "open", "nudge_count": 0,
            "opened_at": "2026-07-13T08:00:00+00:00", "last_movement_at": None,
            "last_proposed_at": None,
            "tasks": {"name": "GBP categories", "assignee_gid": "g1", "assignee_name": "Ivy",
                      "status_key": "in_review", "client_id": "c1", "completed": False, "deleted_at": None},
        },
        {  # unassigned → place proposal
            "id": "e2", "kind": "unassigned", "status": "open", "nudge_count": 0,
            "opened_at": "2026-07-13T08:00:00+00:00", "last_movement_at": None,
            "last_proposed_at": None,
            "tasks": {"name": "New location page", "assignee_gid": None, "assignee_name": None,
                      "status_key": "not_started", "client_id": "c1", "completed": False, "deleted_at": None},
        },
        {  # completed task → skipped (sync will resolve it)
            "id": "e3", "kind": "overdue", "status": "open", "nudge_count": 0,
            "opened_at": "2026-07-13T08:00:00+00:00", "last_movement_at": None,
            "last_proposed_at": None,
            "tasks": {"name": "Done thing", "assignee_gid": "g1", "assignee_name": "Ivy",
                      "status_key": "complete", "client_id": "c1", "completed": True, "deleted_at": None},
        },
        {  # proposed earlier today → renudge-gated out
            "id": "e4", "kind": "overdue", "status": "open", "nudge_count": 2,
            "opened_at": "2026-07-13T08:00:00+00:00", "last_movement_at": None,
            "last_proposed_at": "2026-07-16T06:00:00+00:00",
            "tasks": {"name": "Already chased", "assignee_gid": "g1", "assignee_name": "Ivy",
                      "status_key": "in_progress", "client_id": "c1", "completed": False, "deleted_at": None},
        },
    ]

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def update(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "task_episodes":
                return _Q(eps)
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(E, "get_supabase", lambda: _SB())
    out = E.episode_chase_proposals(date(2026, 7, 16))
    by_action = {p["action"]: p for p in out}
    assert len(out) == 2
    nudge = by_action["nudge_assignee"]
    assert "confirm the status is real" in nudge["reason"] and nudge["perm"] == "nudge_other"
    assert nudge["client_name"] == "Acme" and nudge["args"] == {"task_name": "GBP categories"}
    place = by_action["assign_task"]
    assert "nobody owns it" in place["reason"] and place["perm"] == "assign_task"
    # Priorities: unassigned(50) < stale(60); both present.
    assert nudge["priority"] == 60 and place["priority"] == 50


def test_generator_gated_off(monkeypatch):
    monkeypatch.setattr(settings, "pace_initiative_enabled", False)
    assert E.episode_chase_proposals(date(2026, 7, 16)) == []
