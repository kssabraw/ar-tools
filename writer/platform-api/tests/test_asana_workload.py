"""Tests for the Asana Team Workload orchestration + daily alert (mocked I/O)."""

from __future__ import annotations

import pytest

from config import settings
from services import asana_service, asana_workload, notifications


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "tok")
    monkeypatch.setattr(settings, "asana_workspace_gid", "ws1")
    monkeypatch.setattr(settings, "asana_workload_enabled", True)
    monkeypatch.setattr(settings, "workload_overload_alert_enabled", True)
    monkeypatch.setattr(settings, "asana_effort_field_gid", "f_hrs")
    monkeypatch.setattr(settings, "asana_default_task_hours", 1.0)
    monkeypatch.setattr(settings, "asana_default_weekly_hours", 30.0)
    monkeypatch.setattr(settings, "asana_workload_daily_workdays", 5)
    monkeypatch.setattr(settings, "asana_workload_backlog_weeks", 2.0)


def _task(due, hours=None):
    cf = [{"gid": "f_hrs", "number_value": hours}] if hours is not None else []
    return {"due_on": due, "custom_fields": cf}


async def test_workload_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "")
    report = await asana_workload.build_team_workload()
    assert report["configured"] is False
    assert report["note"] == "not_configured"


async def test_workload_note_when_no_team_list(monkeypatch):
    monkeypatch.setattr(asana_workload, "get_team_members", lambda: [])
    report = await asana_workload.build_team_workload()
    assert report["configured"] is True
    assert report["note"] == "no_team_list"


async def test_workload_aggregates_by_hours(monkeypatch):
    monkeypatch.setattr(
        asana_workload, "get_team_members",
        lambda: [
            {"gid": "minda", "name": "Minda", "weekly_hours": 30},
            {"gid": "ivy", "name": "Ivy", "weekly_hours": 40},
        ],
    )

    async def _users():
        return [{"gid": "minda", "name": "Minda"}, {"gid": "ivy", "name": "Ivy"}]

    tasks_by = {
        "minda": [_task("2026-07-09", 9)],   # 9h one day, daily cap 6 → overloaded
        "ivy": [_task("2026-07-06", 2)],     # fine
    }

    async def _member_tasks(gid):
        return tasks_by[gid]

    monkeypatch.setattr(asana_service, "list_workspace_users", _users)
    monkeypatch.setattr(asana_service, "list_member_open_tasks", _member_tasks)

    report = await asana_workload.build_team_workload()
    assert report["configured"] is True
    assert [m["name"] for m in report["members"]] == ["Minda", "Ivy"]
    assert [m["name"] for m in report["overloaded"]] == ["Minda"]
    assert report["members"][0]["open_hours"] == 9.0


async def test_workload_member_fetch_error_is_best_effort(monkeypatch):
    monkeypatch.setattr(
        asana_workload, "get_team_members",
        lambda: [{"gid": "minda", "name": "Minda"}, {"gid": "ivy", "name": "Ivy"}],
    )

    async def _users():
        return []

    async def _member_tasks(gid):
        if gid == "ivy":
            raise RuntimeError("asana 500")
        return [_task("2026-07-09", 2)]

    monkeypatch.setattr(asana_service, "list_workspace_users", _users)
    monkeypatch.setattr(asana_service, "list_member_open_tasks", _member_tasks)

    report = await asana_workload.build_team_workload()
    hours = {m["name"]: m["open_hours"] for m in report["members"]}
    assert hours == {"Minda": 2.0, "Ivy": 0.0}


# ---------------------------------------------------------------------------
# Daily alert producer
# ---------------------------------------------------------------------------
async def test_alert_emits_when_overloaded(monkeypatch):
    emitted = {}

    def _emit(client_id, kind, title, summary=None, severity="info", payload=None):
        emitted.update(client_id=client_id, kind=kind, title=title, severity=severity, payload=payload)
        return "n1"

    async def _report():
        return {
            "configured": True,
            "members": [],
            "overloaded": [{"gid": "minda", "name": "Minda", "flags": ["9.0h due 2026-07-09 (over 6.0h/day)"]}],
            "thresholds": {},
        }

    monkeypatch.setattr(asana_workload, "build_team_workload", _report)
    monkeypatch.setattr(notifications, "emit", _emit)

    result = await asana_workload.run_workload_alert()
    assert result == {"emitted": True, "overloaded": 1}
    assert emitted["client_id"] is None  # suite-wide
    assert emitted["kind"] == "asana_workload"
    assert emitted["severity"] == "warning"
    assert "Minda" in emitted["title"]
    assert emitted["payload"]["link"] == "/workload"


async def test_alert_silent_when_overload_alert_disabled(monkeypatch):
    monkeypatch.setattr(settings, "workload_overload_alert_enabled", False)
    calls = []

    async def _report():
        return {
            "configured": True,
            "members": [],
            "overloaded": [{"gid": "minda", "name": "Minda", "flags": ["9.0h"]}],
            "thresholds": {},
        }

    monkeypatch.setattr(asana_workload, "build_team_workload", _report)
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: calls.append(1))

    result = await asana_workload.run_workload_alert()
    assert result == {"emitted": False, "reason": "alert_disabled"}
    assert calls == []


async def test_alert_silent_when_none_overloaded(monkeypatch):
    calls = []

    async def _report():
        return {"configured": True, "members": [], "overloaded": [], "thresholds": {}}

    monkeypatch.setattr(asana_workload, "build_team_workload", _report)
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: calls.append(1))

    result = await asana_workload.run_workload_alert()
    assert result == {"emitted": False, "overloaded": 0}
    assert calls == []
