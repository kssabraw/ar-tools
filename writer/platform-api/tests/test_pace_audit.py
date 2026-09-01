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
        {"action": "reassign_task", "decision": "approved", "outcome": "executed", "actor_name": "Kyle"},
        {"action": "reassign_task", "decision": "denied", "outcome": "cancelled", "actor_name": "Kyle"},
        {"action": "set_task_due", "decision": "approved_with_modifications", "outcome": "executed", "actor_name": "Ivy"},
    ]
    stats = pace_audit.decision_stats(rows)
    assert stats["overall"]["total"] == 3
    assert stats["overall"]["approved"] == 1
    assert stats["overall"]["denied"] == 1
    assert stats["overall"]["approved_with_modifications"] == 1
    assert stats["overall"]["executed"] == 2
    assert stats["by_action"]["reassign_task"]["approved"] == 1
    assert stats["by_action"]["reassign_task"]["denied"] == 1
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
