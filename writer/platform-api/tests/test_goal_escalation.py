"""Unit tests for the chronic-emergency escalation pure helpers (no network)."""

from __future__ import annotations

from datetime import date

from services import goal_escalation as ge


# ---------------------------------------------------------------------------
# is_critical / goal_label
# ---------------------------------------------------------------------------
def test_is_critical():
    assert ge.is_critical("behind")
    assert ge.is_critical("overdue")
    assert not ge.is_critical("on_track")
    assert not ge.is_critical("achieved")
    assert not ge.is_critical("no_data")
    assert not ge.is_critical(None)


def test_goal_label_prefers_explicit_label():
    assert ge.goal_label({"label": "Own the pack", "goal_type": "maps_pack_presence"}) == "Own the pack"


def test_goal_label_humanizes_type_when_unlabeled():
    assert ge.goal_label({"label": "", "goal_type": "maps_pack_presence"}) == "local-pack presence"
    assert ge.goal_label({"goal_type": "organic_clicks"}) == "organic clicks"
    assert ge.goal_label({"goal_type": "weird_new_type"}) == "weird new type"


# ---------------------------------------------------------------------------
# initial_behind_since
# ---------------------------------------------------------------------------
def test_initial_behind_since_never_progressed_seeds_from_baseline():
    today = date(2026, 9, 1)
    goal = {"status": "behind", "progress_pct": 0.0, "baseline_date": "2026-06-20"}
    assert ge.initial_behind_since(goal, today) == date(2026, 6, 20)


def test_initial_behind_since_overdue_seeds_from_baseline_even_with_progress():
    today = date(2026, 9, 1)
    goal = {"status": "overdue", "progress_pct": 40.0, "baseline_date": "2026-06-20"}
    assert ge.initial_behind_since(goal, today) == date(2026, 6, 20)


def test_initial_behind_since_recent_slip_starts_clock_today():
    today = date(2026, 9, 1)
    goal = {"status": "behind", "progress_pct": 55.0, "baseline_date": "2026-06-20"}
    assert ge.initial_behind_since(goal, today) == today


def test_initial_behind_since_never_returns_future():
    today = date(2026, 9, 1)
    # A baseline in the future (bad data) must not seed a future behind_since.
    goal = {"status": "behind", "progress_pct": 0.0, "baseline_date": "2026-12-01"}
    assert ge.initial_behind_since(goal, today) == today


def test_initial_behind_since_falls_back_to_created_at_then_today():
    today = date(2026, 9, 1)
    assert ge.initial_behind_since(
        {"status": "behind", "progress_pct": None, "created_at": "2026-07-01T00:00:00Z"}, today
    ) == date(2026, 7, 1)
    assert ge.initial_behind_since({"status": "behind", "progress_pct": None}, today) == today


# ---------------------------------------------------------------------------
# weeks_behind
# ---------------------------------------------------------------------------
def test_weeks_behind():
    today = date(2026, 9, 1)
    assert ge.weeks_behind(date(2026, 9, 1), today) == 0
    assert ge.weeks_behind(date(2026, 8, 25), today) == 1
    assert ge.weeks_behind(date(2026, 6, 20), today) == 10
    assert ge.weeks_behind(None, today) == 0


# ---------------------------------------------------------------------------
# should_escalate
# ---------------------------------------------------------------------------
def test_should_escalate_not_yet_chronic():
    today = date(2026, 9, 1)
    row = {"behind_since": "2026-08-25", "last_escalated_at": None}  # 1 week
    assert not ge.should_escalate(row, today, chronic_weeks=3, reescalate_days=14)


def test_should_escalate_first_time_at_threshold():
    today = date(2026, 9, 1)
    row = {"behind_since": "2026-08-04", "last_escalated_at": None}  # ~4 weeks
    assert ge.should_escalate(row, today, chronic_weeks=3, reescalate_days=14)


def test_should_escalate_throttled_after_recent_shout():
    today = date(2026, 9, 1)
    row = {
        "behind_since": "2026-06-20",
        "last_escalated_at": "2026-08-25T08:00:00Z",  # 7 days ago < 14
    }
    assert not ge.should_escalate(row, today, chronic_weeks=3, reescalate_days=14)


def test_should_escalate_reshouts_after_cadence():
    today = date(2026, 9, 1)
    row = {
        "behind_since": "2026-06-20",
        "last_escalated_at": "2026-08-15T08:00:00Z",  # 17 days ago >= 14
    }
    assert ge.should_escalate(row, today, chronic_weeks=3, reescalate_days=14)


# ---------------------------------------------------------------------------
# build_escalation
# ---------------------------------------------------------------------------
def _goal_eval():
    return {
        "label": "Local pack presence",
        "goal_type": "maps_pack_presence",
        "status": "behind",
        "current_value": 6.2,
        "effective_target": 35.0,
    }


def test_build_escalation_leads_with_weeks_and_gap():
    note = ge.build_escalation("First Class Roofing", _goal_eval(), 6, 2, "Local-pack is critically behind.")
    assert note["title"] == "STILL CRITICAL (week 6): First Class Roofing — Local pack presence"
    assert "behind for 6 weeks" in note["summary"]
    assert "now 6.2 vs target 35" in note["summary"]
    assert "2 open alerts" in note["summary"]
    assert "Local-pack is critically behind." in note["summary"]


def test_build_escalation_notes_when_no_fresh_alerts():
    note = ge.build_escalation("Acme", _goal_eval(), 4, 0, None)
    assert "No fresh alerts have fired" in note["summary"]
    # No reasoning available → summary is just the deterministic lead.
    assert note["summary"].endswith("critically behind.")


def test_build_escalation_singular_week():
    note = ge.build_escalation("Acme", _goal_eval(), 1, 1, None)
    assert "behind for 1 week" in note["summary"] and "1 open alert." in note["summary"]


# ---------------------------------------------------------------------------
# run_goal_escalation_sweep — flow (fake Supabase, no network)
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, table, store):
        self.table_name = table
        self.store = store
        self._count = None

    # chainable no-ops that just return self
    def select(self, *a, **k):
        if k.get("count") == "exact":
            self._count = self.store["counts"].get(self.table_name, 0)
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, row):
        self.store["inserts"].append((self.table_name, row))
        self._insert_row = {**row, "id": "esc-1", "escalation_count": 0}
        return self

    def update(self, patch):
        self.store["updates"].append((self.table_name, patch))
        return self

    def execute(self):
        if getattr(self, "_insert_row", None) is not None:
            return type("R", (), {"data": [self._insert_row], "count": None})()
        data = self.store["reads"].get(self.table_name, [])
        return type("R", (), {"data": data, "count": self._count})()


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeQuery(name, self.store)


def _make_store(open_rows):
    return {
        "reads": {
            "campaign_goals": [{"client_id": "c1"}],
            "goal_escalations": open_rows,
            "clients": [{"name": "First Class Roofing"}],
            "strategy_reviews": [{"assessment": "Local-pack is critically behind."}],
        },
        "counts": {"rank_alerts": 1, "maps_alerts": 2},
        "inserts": [],
        "updates": [],
    }


def test_sweep_opens_and_escalates_a_chronic_goal(monkeypatch):
    from services import campaign_goals
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)

    store = _make_store(open_rows=[])  # no existing escalation
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))

    # A goal behind since the campaign started, never progressed → chronic now.
    goal = {
        "id": "g1", "goal_type": "maps_pack_presence", "label": "Local pack presence",
        "status": "behind", "progress_pct": 0.0, "baseline_date": "2026-06-01",
        "baseline_value": 6.0, "current_value": 6.2, "effective_target": 35.0,
    }
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [goal])

    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()

    assert stats["opened"] == 1 and stats["escalated"] == 1
    assert len(emitted) == 1
    e = emitted[0]
    assert e["kind"] == "goal_chronic" and e["severity"] == "critical"
    assert e["client_id"] == "c1"
    assert "STILL CRITICAL" in e["title"]
    assert "Local-pack is critically behind." in e["summary"]  # reasoning carried
    # last_escalated_at + count bump was written back.
    assert any(t == "goal_escalations" and "last_escalated_at" in p for t, p in store["updates"])


def test_sweep_resolves_when_goal_recovers(monkeypatch):
    from services import campaign_goals
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)

    open_row = {
        "id": "esc-9", "goal_id": "g1", "goal_label": "Local pack presence",
        "behind_since": "2026-06-01", "last_escalated_at": "2026-08-20T08:00:00Z",
        "escalation_count": 2,
    }
    store = _make_store(open_rows=[open_row])
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))

    # The goal is now on_track → the open escalation must resolve.
    goal = {"id": "g1", "goal_type": "maps_pack_presence", "status": "on_track", "current_value": 36}
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [goal])

    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()

    assert stats["resolved"] == 1 and stats["escalated"] == 0
    assert any(t == "goal_escalations" and p.get("status") == "resolved" for t, p in store["updates"])
    # It had escalated before, so a recovery notice is emitted.
    assert emitted and emitted[0]["kind"] == "goal_recovered"


def test_sweep_disabled_is_a_noop(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", False)
    called = {"n": 0}
    monkeypatch.setattr(ge, "get_supabase", lambda: called.__setitem__("n", called["n"] + 1))
    stats = ge.run_goal_escalation_sweep()
    assert all(stats[k] == 0 for k in ("opened", "escalated", "resolved", "clients", "recovery_enqueued"))
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Recovery dispatch (PRD PR 2): a due goal enqueues ONE goal_recovery run per
# client (oldest-behind first, capped per tick) and the FINISHED run sends the
# message; the bare alarm only fires when a run is impossible.
# ---------------------------------------------------------------------------
def _chronic_goal(gid="g1", behind="2026-06-01"):
    return {
        "id": gid, "goal_type": "maps_pack_presence", "label": f"Goal {gid}",
        "status": "behind", "progress_pct": 0.0, "baseline_date": behind,
        "baseline_value": 6.0, "current_value": 6.2, "effective_target": 35.0,
    }


def _recovery_gate(monkeypatch, open_: bool):
    from services import goal_recovery
    monkeypatch.setattr(goal_recovery, "gate_open", lambda: open_)
    monkeypatch.setattr(goal_recovery, "clients_recovered_within", lambda days: set())


def test_sweep_enqueues_recovery_run_instead_of_bare_alarm(monkeypatch):
    from services import campaign_goals, goal_recovery
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)
    monkeypatch.setattr(settings, "goal_recovery_max_runs_per_tick", 5)
    store = _make_store(open_rows=[])
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [_chronic_goal()])
    _recovery_gate(monkeypatch, True)
    enqueued = []
    monkeypatch.setattr(goal_recovery, "enqueue_recovery_run",
                        lambda cid, goals: (enqueued.append((cid, goals)), ("enqueued", "r-1"))[1])
    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()

    assert stats["opened"] == 1 and stats["recovery_enqueued"] == 1
    assert stats["escalated"] == 0 and emitted == []  # the run sends the message
    assert enqueued[0][0] == "c1"
    assert enqueued[0][1][0]["goal_id"] == "g1" and enqueued[0][1][0]["escalation_id"] == "esc-1"
    # NOT stamped — the finished run stamps, so a failed run retries next tick.
    assert not any(t == "goal_escalations" and "last_escalated_at" in p for t, p in store["updates"])


def test_sweep_falls_back_to_bare_alarm_when_run_impossible(monkeypatch):
    from services import campaign_goals, goal_recovery
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)
    store = _make_store(open_rows=[])
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [_chronic_goal()])
    _recovery_gate(monkeypatch, True)
    monkeypatch.setattr(goal_recovery, "enqueue_recovery_run", lambda cid, goals: ("failed", None))
    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()

    assert stats["escalated"] == 1 and len(emitted) == 1
    assert emitted[0]["kind"] == "goal_chronic" and "STILL CRITICAL" in emitted[0]["title"]
    assert any(t == "goal_escalations" and "last_escalated_at" in p for t, p in store["updates"])


def test_sweep_in_flight_run_neither_alarms_nor_stamps(monkeypatch):
    from services import campaign_goals, goal_recovery
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)
    store = _make_store(open_rows=[])
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [_chronic_goal()])
    _recovery_gate(monkeypatch, True)
    monkeypatch.setattr(goal_recovery, "enqueue_recovery_run", lambda cid, goals: ("in_flight", None))
    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()
    assert stats["recovery_in_flight"] == 1 and stats["escalated"] == 0 and emitted == []
    assert not any(t == "goal_escalations" and "last_escalated_at" in p for t, p in store["updates"])


def test_sweep_cap_defers_the_newest_behind_client_without_alarm(monkeypatch):
    """Two chronic clients, cap 1: the oldest-behind gets the run; the other is
    NOT escalated today at all (no bare alarm, no stamp) and rolls forward."""
    from services import campaign_goals, goal_recovery
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)
    monkeypatch.setattr(settings, "goal_recovery_max_runs_per_tick", 1)
    store = _make_store(open_rows=[])
    store["reads"]["campaign_goals"] = [{"client_id": "c-new"}, {"client_id": "c-old"}]
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))
    goals_by_client = {"c-new": [_chronic_goal("g-new", "2026-07-20")], "c-old": [_chronic_goal("g-old", "2026-06-01")]}
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: goals_by_client[cid])
    _recovery_gate(monkeypatch, True)
    enqueued = []
    monkeypatch.setattr(goal_recovery, "enqueue_recovery_run",
                        lambda cid, goals: (enqueued.append(cid), ("enqueued", "r"))[1])
    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()

    assert enqueued == ["c-old"]
    assert stats["recovery_enqueued"] == 1 and stats["recovery_deferred"] == 1
    assert stats["escalated"] == 0 and emitted == []


def test_sweep_gate_closed_keeps_the_949_behaviour(monkeypatch):
    from services import campaign_goals
    from config import settings

    monkeypatch.setattr(settings, "goal_escalation_enabled", True)
    monkeypatch.setattr(settings, "goal_escalation_chronic_weeks", 3)
    store = _make_store(open_rows=[])
    monkeypatch.setattr(ge, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [_chronic_goal()])
    _recovery_gate(monkeypatch, False)
    emitted = []
    monkeypatch.setattr(ge.notifications, "emit", lambda **kw: emitted.append(kw))

    stats = ge.run_goal_escalation_sweep()
    assert stats["escalated"] == 1 and len(emitted) == 1 and stats["recovery_enqueued"] == 0
