"""Tests for the PACE action log (services/pace_audit.py).

Pure helpers (loggable-action filter, task snapshot, target derivation, partial-
selection modifications, decision-rate rollup, history formatting) + the impure
``record`` / ``run_and_log`` flow with Supabase and the snapshot read mocked —
proving before/after capture, that a failed run is logged then re-raised, that a
non-campaign action is never logged, and that logging is best-effort (a DB error
never surfaces).
"""

from __future__ import annotations

import pytest

from services import pace_audit
from services.pace_auth import ActionContext


def _ctx(pid="p1", role="staff", source="web"):
    return ActionContext(profile_id=pid, role=role, source=source)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_is_logged():
    assert pace_audit.is_logged("reassign_task")
    assert pace_audit.is_logged("intervention_disposition")
    # Reads are NOT logged.
    assert not pace_audit.is_logged("generate_pace_report")
    assert not pace_audit.is_logged("write_client_pulse")
    assert not pace_audit.is_logged("pace_history")
    assert not pace_audit.is_logged(None)


def test_task_snapshot_projects_key_fields():
    row = {"name": "GBP audit", "assignee_name": "Ivy", "status_key": "in_progress",
           "due_date": "2026-09-10", "category": "gbp", "est_hours": 2,
           "completed": False, "extra": "dropped", "id": "t1"}
    snap = pace_audit.task_snapshot(row)
    assert snap == {"name": "GBP audit", "assignee_name": "Ivy", "assignee_id": None,
                    "status_key": "in_progress", "due_date": "2026-09-10",
                    "category": "gbp", "est_hours": 2, "completed": False}
    assert "extra" not in snap and "id" not in snap
    assert pace_audit.task_snapshot(None) is None


def test_target_from_args():
    assert pace_audit.target_from_args("reassign_task",
                                       {"task_id": "t9", "task_name": "X"}) == {
        "target_type": "task", "target_id": "t9", "target_name": "X"}
    # rename carries old_name as the display name.
    assert pace_audit.target_from_args("rename_task",
                                       {"task_id": "t2", "old_name": "Old"})["target_name"] == "Old"
    assert pace_audit.target_from_args("generate_client_month", {"month": "2026-09-01"}) == {
        "target_type": "month", "target_id": "2026-09-01", "target_name": None}
    assert pace_audit.target_from_args("write_client_pulse", {})["target_type"] == "client"


def test_selection_modifications():
    # Everything approved → no modification.
    assert pace_audit.selection_modifications(3, [1, 2, 3]) is None
    # Partial approval → the approved/dropped split.
    assert pace_audit.selection_modifications(3, [1, 3]) == {
        "approved": [1, 3], "dropped": [2], "total": 3}
    # Out-of-range picks are ignored.
    assert pace_audit.selection_modifications(2, [1, 5]) == {
        "approved": [1], "dropped": [2], "total": 2}


def test_decision_stats_rollup():
    rows = [
        {"action": "reassign_task", "decision": "approved", "outcome": "executed", "actor_name": "Kyle",
         "reverted_at": "2026-09-02T00:00:00Z"},
        {"action": "reassign_task", "decision": "denied", "outcome": "cancelled", "actor_name": "Kyle"},
        {"action": "set_task_due", "decision": "approved_with_modifications", "outcome": "executed", "actor_name": "Ivy"},
    ]
    stats = pace_audit.decision_stats(rows)
    assert stats["overall"]["total"] == 3
    assert stats["overall"]["approved"] == 1
    assert stats["overall"]["denied"] == 1
    assert stats["overall"]["approved_with_modifications"] == 1
    assert stats["overall"]["executed"] == 2
    assert stats["overall"]["reverted"] == 1  # the executed reassign was undone
    assert stats["by_action"]["reassign_task"]["approved"] == 1
    assert stats["by_action"]["reassign_task"]["denied"] == 1
    assert stats["by_action"]["reassign_task"]["reverted"] == 1
    assert stats["by_actor"]["Kyle"]["total"] == 2
    assert stats["by_actor"]["Ivy"]["approved_with_modifications"] == 1


def test_format_history_lines():
    rows = [
        {"created_at": "2026-09-01T10:00:00Z", "decision": "approved", "outcome": "executed",
         "actor_name": "Kyle", "client_name": "Acme", "reason": "reassign X to Ivy", "action": "reassign_task"},
        {"created_at": "2026-09-01T11:00:00Z", "decision": "denied", "outcome": "cancelled",
         "actor_name": "Ivy", "client_name": "Acme", "reason": "bump due", "action": "set_task_due"},
    ]
    text = pace_audit.format_history(rows)
    assert "Acme" in text and "reassign X to Ivy" in text and "[cancelled]" in text
    assert pace_audit.format_history([]).startswith("No PACE actions")


# ---------------------------------------------------------------------------
# record — best-effort, gated, filtered
# ---------------------------------------------------------------------------
class _FakeTable:
    def __init__(self, sink):
        self._sink = sink

    def insert(self, row):
        self._sink.append(row)
        return self

    def execute(self):
        return type("R", (), {"data": [{}]})()


class _FakeSupabase:
    def __init__(self, sink):
        self._sink = sink

    def table(self, _name):
        return _FakeTable(self._sink)


def test_record_writes_row_when_enabled(monkeypatch):
    sink: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "get_supabase", lambda: _FakeSupabase(sink))
    pace_audit.record(action="reassign_task", origin="conversational", outcome="executed",
                      decision="approved", context=_ctx(), client_id="c1", client_name="Acme",
                      reason="reassign X", args={"task_id": "t1"})
    assert len(sink) == 1
    row = sink[0]
    assert row["action"] == "reassign_task" and row["decision"] == "approved"
    assert row["actor_profile_id"] == "p1" and row["actor_source"] == "web"
    assert row["client_name"] == "Acme"


def test_record_skips_when_disabled(monkeypatch):
    sink: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", False)
    monkeypatch.setattr(pace_audit, "get_supabase", lambda: _FakeSupabase(sink))
    pace_audit.record(action="reassign_task", origin="conversational", outcome="executed")
    assert sink == []


def test_record_skips_non_logged_action(monkeypatch):
    sink: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "get_supabase", lambda: _FakeSupabase(sink))
    pace_audit.record(action="generate_pace_report", origin="conversational", outcome="executed")
    assert sink == []


def test_record_is_best_effort(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "get_supabase", _boom)
    # Must not raise — a logging failure never breaks the action.
    pace_audit.record(action="reassign_task", origin="conversational", outcome="executed")


# ---------------------------------------------------------------------------
# run_and_log — before/after capture, failure logging + re-raise, read passthrough
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_and_log_success_captures_before_after(monkeypatch):
    calls: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "record", lambda **kw: calls.append(kw))
    # Simulate a task that changed assignee across the run.
    states = iter([{"assignee_name": "unassigned", "status_key": "in_progress"},
                   {"assignee_name": "Ivy", "status_key": "in_progress"}])
    monkeypatch.setattr(pace_audit, "_read_task", lambda tid: next(states) if tid else None)

    result = await pace_audit.run_and_log(
        lambda: "✅ Reassigned to Ivy.", action="reassign_task", context=_ctx(),
        client_id="c1", args={"task_id": "t1", "task_name": "GBP audit"},
        origin="conversational", decision="approved", reason="reassign to Ivy")

    assert result == "✅ Reassigned to Ivy."
    assert len(calls) == 1
    kw = calls[0]
    assert kw["outcome"] == "executed" and kw["decision"] == "approved"
    assert kw["before"]["assignee_name"] == "unassigned"
    assert kw["after"]["assignee_name"] == "Ivy"
    assert kw["result"] == "✅ Reassigned to Ivy."
    assert kw["target_type"] == "task" and kw["target_id"] == "t1"


@pytest.mark.asyncio
async def test_run_and_log_failure_logs_then_reraises(monkeypatch):
    calls: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "record", lambda **kw: calls.append(kw))
    monkeypatch.setattr(pace_audit, "_read_task", lambda tid: {"assignee_name": "Ivy"})

    def _boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await pace_audit.run_and_log(_boom, action="set_task_due", context=_ctx(),
                                     client_id="c1", args={"task_id": "t1"}, origin="conversational")
    assert len(calls) == 1 and calls[0]["outcome"] == "failed"
    assert "nope" in (calls[0]["error"] or "")


@pytest.mark.asyncio
async def test_run_and_log_awaits_async_run(monkeypatch):
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "record", lambda **kw: None)
    monkeypatch.setattr(pace_audit, "_read_task", lambda tid: None)

    async def _async_run():
        return "done"

    assert await pace_audit.run_and_log(_async_run, action="nudge_assignee", context=_ctx(),
                                        client_id="c1", args={"task_id": "t1"},
                                        origin="conversational") == "done"


@pytest.mark.asyncio
async def test_run_and_log_non_logged_action_runs_without_logging(monkeypatch):
    calls: list = []
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    monkeypatch.setattr(pace_audit, "record", lambda **kw: calls.append(kw))
    # A read (report) still runs but produces no row + no snapshot read.
    monkeypatch.setattr(pace_audit, "_read_task", lambda tid: pytest.fail("should not snapshot a read"))

    out = await pace_audit.run_and_log(lambda: "report text", action="generate_pace_report",
                                       context=_ctx(), client_id="c1", args={}, origin="conversational")
    assert out == "report text" and calls == []


# ---------------------------------------------------------------------------
# Seam wiring — each execution/decision path routes through the ledger
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conversational_action_routes_through_run_and_log(monkeypatch):
    """pace_agent._run_pace_action logs a confirmed action (origin=conversational,
    decision=approved) carrying the confirm reason + requester."""
    from services import pace_agent

    captured: dict = {}

    async def _fake(fn, **kw):
        captured.update(kw)
        return "✅ ran"

    monkeypatch.setattr(pace_audit, "run_and_log", _fake)
    out = await pace_agent._run_pace_action("reassign_task", "c1", {"task_id": "t1"}, _ctx(),
                                            reason="reassign X to Ivy", requester="p1",
                                            client_name="Acme")
    assert out == "✅ ran"
    assert captured["action"] == "reassign_task"
    assert captured["origin"] == "conversational" and captured["decision"] == "approved"
    assert captured["reason"] == "reassign X to Ivy" and captured["client_name"] == "Acme"
    assert captured["requester"] == "p1"


@pytest.mark.asyncio
async def test_chase_selection_logs_partial_as_modifications(monkeypatch):
    """execute_plan_selection logs each RUN item; a partial approval is recorded
    as approved_with_modifications with the approved/dropped split."""
    from services import pace_proposals

    captured: list = []

    async def _fake(fn, **kw):
        captured.append(kw)
        return "✅ done"

    monkeypatch.setattr(pace_audit, "run_and_log", _fake)
    items = [
        {"index": 1, "action": "reassign_task", "client_id": "c1", "client_name": "Acme",
         "args": {"task_id": "t1"}, "reason": "r1", "min_role": None},
        {"index": 2, "action": "set_task_due", "client_id": "c1", "client_name": "Acme",
         "args": {"task_id": "t2"}, "reason": "r2", "min_role": None},
    ]
    await pace_proposals.execute_plan_selection(items, [1], _ctx(role="admin"),
                                                origin="chase_plan", chase_plan_date="2026-09-01")
    assert len(captured) == 1  # only item 1 was selected
    assert captured[0]["origin"] == "chase_plan"
    assert captured[0]["decision"] == "approved_with_modifications"
    assert captured[0]["modifications"] == {"approved": [1], "dropped": [2], "total": 2}
    assert captured[0]["chase_plan_date"] == "2026-09-01"


@pytest.mark.asyncio
async def test_intervention_execute_actions_logs(monkeypatch):
    """pace_interventions._execute_actions logs each executed sub-action with
    origin=intervention + the intervention id."""
    from services import pace_interventions
    from services.pace_actions import PACE_ACTIONS

    captured: list = []

    async def _fake(fn, **kw):
        captured.append(kw)
        return "✅ done"

    monkeypatch.setattr(pace_audit, "run_and_log", _fake)
    monkeypatch.setitem(PACE_ACTIONS, "_faketest", {
        "label": "x",
        "stage": lambda ctx, cid, args: ("confirm", {"task_id": "t1", "_confirm": "do", "_requester": None}),
        "run": lambda ctx, cid, args: "ran",
    })
    res = await pace_interventions._execute_actions(
        [{"action": "_faketest", "client_id": "c1", "client_name": "Acme", "args": {}, "reason": "fix"}],
        _ctx(), intervention_id="i1", decision="approved")
    assert res["ran"] == ["✅ done"]
    assert captured[0]["origin"] == "intervention" and captured[0]["intervention_id"] == "i1"
    assert captured[0]["decision"] == "approved"


def test_intervention_disposition_decision_mapping(monkeypatch):
    """_log_disposition maps each disposition → the right decision + outcome and
    carries the conditions as modifications."""
    from services import pace_interventions

    calls: list = []
    monkeypatch.setattr(pace_audit, "record_decision", lambda **kw: calls.append(kw))
    row = {"id": "i1", "scope_client_id": "c1", "title": "Overload fix"}
    pace_interventions._log_disposition(row, _ctx(), "approved", None, {"ok": True, "status": "executed"})
    pace_interventions._log_disposition(row, _ctx(), "denied", "too risky", {"ok": True, "status": "denied"})
    pace_interventions._log_disposition(row, _ctx(), "deferred", None, {"ok": True, "status": "deferred"})
    pace_interventions._log_disposition(row, _ctx(), "approved_with_modifications", "only Ivy",
                                        {"ok": False, "status": "proposed"})
    assert [c["decision"] for c in calls] == [
        "approved", "denied", "deferred", "approved_with_modifications"]
    assert [c["outcome"] for c in calls] == ["executed", "denied", "deferred", "skipped"]
    assert calls[1]["modifications"] == {"conditions": "too risky"}
    assert all(c["action"] == pace_audit.INTERVENTION_DISPOSITION for c in calls)
    # A failed defer (bad date) records nothing.
    pace_interventions._log_disposition(row, _ctx(), "deferred", None, {"ok": False, "status": "proposed"})
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# v2 — revert detection (pure)
# ---------------------------------------------------------------------------
def test_changed_fields():
    before = {"assignee_name": "unassigned", "status_key": "in_progress", "due_date": "2026-09-10"}
    after = {"assignee_name": "Ivy", "status_key": "in_progress", "due_date": "2026-09-10"}
    assert pace_audit.changed_fields(before, after) == ["assignee_name"]
    assert pace_audit.changed_fields(None, after) == []


def test_classify_revert():
    before = {"assignee_name": "unassigned", "status_key": "in_progress"}
    after = {"assignee_name": "Ivy", "status_key": "in_progress"}
    # Back to the pre-PACE value → reverted.
    rev = pace_audit.classify_revert(before, after, {"assignee_name": "unassigned", "status_key": "in_progress"})
    assert rev and rev["kind"] == "reverted" and rev["field"] == "assignee_name"
    # Changed to a third value → overridden.
    ov = pace_audit.classify_revert(before, after, {"assignee_name": "Marcus", "status_key": "in_progress"})
    assert ov and ov["kind"] == "overridden" and ov["to_current"] == "Marcus"
    # Still PACE's value → None.
    assert pace_audit.classify_revert(before, after, {"assignee_name": "Ivy", "status_key": "in_progress"}) is None
    # No current state (deleted) → None.
    assert pace_audit.classify_revert(before, after, None) is None


def test_classify_revert_prefers_revert_over_override():
    before = {"assignee_name": "unassigned", "status_key": "blocked"}
    after = {"assignee_name": "Ivy", "status_key": "in_progress"}
    # assignee overridden (→Marcus) but status reverted (→blocked): revert wins.
    detail = pace_audit.classify_revert(before, after, {"assignee_name": "Marcus", "status_key": "blocked"})
    assert detail["kind"] == "reverted" and detail["field"] == "status_key"


# ---------------------------------------------------------------------------
# v2 — learning signals + proposal penalty (pure)
# ---------------------------------------------------------------------------
def test_learning_signals_reject_rate():
    rows = [
        {"action": "reassign_task", "client_id": "c1", "decision": "denied", "outcome": "cancelled"},
        {"action": "reassign_task", "client_id": "c1", "decision": "denied", "outcome": "cancelled"},
        {"action": "reassign_task", "client_id": "c1", "decision": "approved", "outcome": "executed",
         "reverted_at": "x"},
        {"action": "reassign_task", "client_id": "c1", "decision": "approved", "outcome": "executed"},
    ]
    sig = pace_audit.learning_signals(rows)
    ba = sig["by_action"]["reassign_task"]
    assert ba["total"] == 4 and ba["denied"] == 2 and ba["reverted"] == 1
    # reject_rate = (denied 2 + reverted 1) / 4
    assert ba["reject_rate"] == 0.75
    assert sig["by_client_action"]["c1::reassign_task"]["reject_rate"] == 0.75


def test_proposal_penalty_gated_and_scaled(monkeypatch):
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_enabled", True)
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_min_samples", 4)
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_reject_threshold", 0.6)
    # Below min samples → no penalty.
    thin = {"by_client_action": {}, "by_action": {"reassign_task": {"total": 2, "denied": 2, "reverted": 0, "reject_rate": 1.0}}}
    assert pace_audit.proposal_penalty("reassign_task", "c1", thin) == (1.0, None)
    # Above threshold with enough samples → demoted (<1) + a note.
    heavy = {"by_client_action": {"c1::reassign_task": {"total": 5, "denied": 4, "reverted": 0, "reject_rate": 0.8}},
             "by_action": {}}
    factor, note = pace_audit.proposal_penalty("reassign_task", "c1", heavy)
    assert 0.2 <= factor < 1.0 and note and "4 of 5" in note
    # Below the reject threshold → no penalty even with samples.
    ok = {"by_client_action": {}, "by_action": {"reassign_task": {"total": 10, "denied": 1, "reverted": 0, "reject_rate": 0.1}}}
    assert pace_audit.proposal_penalty("reassign_task", "c1", ok) == (1.0, None)


def test_proposal_penalty_disabled_is_inert(monkeypatch):
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_enabled", False)
    heavy = {"by_client_action": {"c1::reassign_task": {"total": 5, "denied": 5, "reverted": 0, "reject_rate": 1.0}}, "by_action": {}}
    assert pace_audit.proposal_penalty("reassign_task", "c1", heavy) == (1.0, None)


def test_proposal_penalty_agency_fallback(monkeypatch):
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_enabled", True)
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_min_samples", 4)
    monkeypatch.setattr(pace_audit.settings, "pace_audit_learning_reject_threshold", 0.6)
    # No per-client history → falls back to agency-wide per-action.
    sig = {"by_client_action": {}, "by_action": {"nudge_assignee": {"total": 6, "denied": 5, "reverted": 0, "reject_rate": 0.83}}}
    factor, note = pace_audit.proposal_penalty("nudge_assignee", "cX", sig)
    assert factor < 1.0 and note


def test_build_learning_digest():
    rows = [
        {"action": "reassign_task", "decision": "denied", "outcome": "cancelled"},
        {"action": "reassign_task", "decision": "denied", "outcome": "cancelled"},
        {"action": "set_task_due", "decision": "approved", "outcome": "executed", "reverted_at": "x"},
    ]
    text = pace_audit.build_learning_digest(rows)
    assert "learning digest" in text.lower()
    assert "reassign_task" in text and "reverted" in text.lower()
    assert pace_audit.build_learning_digest([]) == ""


# ---------------------------------------------------------------------------
# v2 — wiring: dropped items logged as denials; chase penalty; revert sweep
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dropped_chase_items_logged_as_denied(monkeypatch):
    from services import pace_proposals

    async def _fake_ral(fn, **kw):
        return "✅ done"

    decisions: list = []
    monkeypatch.setattr(pace_audit, "run_and_log", _fake_ral)
    monkeypatch.setattr(pace_audit, "record_decision", lambda **kw: decisions.append(kw))
    items = [
        {"index": 1, "action": "reassign_task", "client_id": "c1", "client_name": "Acme",
         "args": {"task_id": "t1", "task_name": "A"}, "reason": "r1", "min_role": None},
        {"index": 2, "action": "set_task_due", "client_id": "c1", "client_name": "Acme",
         "args": {"task_id": "t2", "task_name": "B"}, "reason": "r2", "min_role": None},
        {"index": 3, "action": "nudge_assignee", "client_id": "c1", "client_name": "Acme",
         "args": {"task_id": "t3", "task_name": "C"}, "reason": "r3", "min_role": None},
    ]
    # Approve only item 1 → items 2 and 3 are dropped → logged as denied.
    await pace_proposals.execute_plan_selection(items, [1], _ctx(role="admin"), origin="chase_plan")
    assert len(decisions) == 2
    assert {d["target_id"] for d in decisions} == {"t2", "t3"}
    assert all(d["decision"] == "denied" and d["outcome"] == "cancelled" for d in decisions)


@pytest.mark.asyncio
async def test_build_chase_plan_demotes_when_learning_on(monkeypatch):
    from services import pace_proposals

    monkeypatch.setattr(pace_proposals.settings, "pace_audit_learning_enabled", True)
    monkeypatch.setattr(pace_proposals.settings, "pace_chase_max_items", 10)
    monkeypatch.setattr(pace_audit, "_learning_signals_window", lambda: {"_sentinel": True})

    def _penalty(action, client_id, signals=None):
        assert signals == {"_sentinel": True}  # precomputed once, passed in
        return (0.3, "declined 4 of 5 recent times") if action == "reassign_task" else (1.0, None)

    monkeypatch.setattr(pace_audit, "proposal_penalty", _penalty)

    def _gen(today):
        return [
            {"action": "reassign_task", "client_id": "c1", "client_name": "Acme",
             "args": {"task_id": "t1"}, "reason": "reassign A", "priority": 100, "perm": "reassign_task"},
            {"action": "nudge_assignee", "client_id": "c1", "client_name": "Acme",
             "args": {"task_id": "t2"}, "reason": "nudge B", "priority": 90, "perm": "nudge_other"},
        ]

    monkeypatch.setattr(pace_proposals, "PROPOSAL_GENERATORS", [_gen])
    # Stub staging so items resolve cleanly to confirmable actions.
    async def _stage_ok(fn, *a):
        return ("confirm", {"task_id": "t", "_confirm": "do", "_requester": None})
    monkeypatch.setattr(pace_proposals, "_call_action", _stage_ok)

    plan = await pace_proposals.build_chase_plan()
    reassign = next(i for i in plan["items"] if i["action"] == "reassign_task")
    # Penalized 100*0.3=30 < nudge 90 → nudge is now item 1, reassign demoted.
    assert plan["items"][0]["action"] == "nudge_assignee"
    assert "declined 4 of 5" in reassign["reason"]


def test_run_revert_sweep_marks_reverted(monkeypatch):
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    updates: list = []

    # A chainable query stub: every builder method returns self (and `.not_` is a
    # property that also returns self), so any Supabase chain the sweep builds is
    # accepted; only .execute()/.update() carry behavior.
    class _Chain:
        def __init__(self, kind):
            self._kind = kind
        def __getattr__(self, _name):
            return lambda *a, **k: self  # select/eq/is_/gte/in_/limit → self
        @property
        def not_(self):
            return self
        def update(self, patch):
            self._kind = "update"
            self._patch = patch
            return self
        def execute(self):
            if self._kind == "update":
                updates.append(self._patch)
                return type("R", (), {"data": [{}]})()
            if self._kind == "tasks":
                return type("R", (), {"data": [
                    {"id": "t1", "assignee_name": "unassigned", "status_key": "in_progress",
                     "assignee_id": None, "due_date": None, "category": None,
                     "est_hours": None, "completed": False, "name": "A"}]})()
            # pace_action_log select: one executed row whose assignee is now back
            # to the pre-PACE value → a revert.
            return type("R", (), {"data": [
                {"id": "row1", "target_id": "t1",
                 "before": {"assignee_name": "unassigned"},
                 "after": {"assignee_name": "Ivy"}}]})()

    class _FakeSupa:
        def table(self, name):
            return _Chain("tasks" if name == "tasks" else "log")

    monkeypatch.setattr(pace_audit, "get_supabase", lambda: _FakeSupa())
    result = pace_audit.run_revert_sweep()
    assert result["reverted"] == 1
    assert updates and updates[0]["revert_detail"]["kind"] == "reverted"
    assert "reverted_at" in updates[0]


def test_run_revert_sweep_ignores_override(monkeypatch):
    """A field changed to a THIRD value (normal forward progression / a later
    PACE action) is NOT marked — only exact reverts count."""
    monkeypatch.setattr(pace_audit.settings, "pace_audit_enabled", True)
    updates: list = []

    class _Chain:
        def __init__(self, kind):
            self._kind = kind
        def __getattr__(self, _name):
            return lambda *a, **k: self
        @property
        def not_(self):
            return self
        def update(self, patch):
            self._kind = "update"
            self._patch = patch
            return self
        def execute(self):
            if self._kind == "update":
                updates.append(self._patch)
                return type("R", (), {"data": [{}]})()
            if self._kind == "tasks":
                # current status is a THIRD value (forward progression) → override.
                return type("R", (), {"data": [
                    {"id": "t1", "assignee_name": "Ivy", "status_key": "sent_to_client",
                     "assignee_id": None, "due_date": None, "category": None,
                     "est_hours": None, "completed": False, "name": "A"}]})()
            return type("R", (), {"data": [
                {"id": "row1", "target_id": "t1",
                 "before": {"status_key": "in_progress"},
                 "after": {"status_key": "in_qa"}}]})()

    class _FakeSupa:
        def table(self, name):
            return _Chain("tasks" if name == "tasks" else "log")

    monkeypatch.setattr(pace_audit, "get_supabase", lambda: _FakeSupa())
    result = pace_audit.run_revert_sweep()
    assert result["reverted"] == 0
    assert updates == []  # nothing marked
