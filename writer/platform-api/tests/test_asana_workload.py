"""Tests for the Asana Team Workload orchestration (mocked Asana calls)."""

from __future__ import annotations

import pytest

from config import settings
from services import asana_service, asana_workload


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "tok")
    monkeypatch.setattr(settings, "asana_workspace_gid", "ws1")
    monkeypatch.setattr(settings, "asana_workload_enabled", True)
    monkeypatch.setattr(settings, "asana_workload_max_open", 25)
    monkeypatch.setattr(settings, "asana_workload_max_due_same_day", 2)


async def test_workload_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "")
    report = await asana_workload.build_team_workload()
    assert report["configured"] is False
    assert report["members"] == []
    assert report["note"] == "not_configured"


async def test_workload_note_when_no_team_list(monkeypatch):
    monkeypatch.setattr(settings, "asana_team_member_gids", "")
    report = await asana_workload.build_team_workload()
    assert report["configured"] is True
    assert report["note"] == "no_team_list"
    assert report["members"] == []


async def test_workload_aggregates_team(monkeypatch):
    monkeypatch.setattr(settings, "asana_team_member_gids", "minda, ivy")

    async def _users():
        return [{"gid": "minda", "name": "Minda"}, {"gid": "ivy", "name": "Ivy"}]

    tasks_by = {
        "minda": [{"due_on": "2026-07-09"}, {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"}],
        "ivy": [{"due_on": "2026-07-06"}],
    }

    async def _member_tasks(gid):
        return tasks_by[gid]

    monkeypatch.setattr(asana_service, "list_workspace_users", _users)
    monkeypatch.setattr(asana_service, "list_member_open_tasks", _member_tasks)

    report = await asana_workload.build_team_workload()
    assert report["configured"] is True
    # Sorted by open_count desc → Minda first; only Minda overloaded (3 > 2 same day).
    assert [m["name"] for m in report["members"]] == ["Minda", "Ivy"]
    assert [m["name"] for m in report["overloaded"]] == ["Minda"]
    minda = report["members"][0]
    assert minda["worst_same_day"] == {"date": "2026-07-09", "count": 3}


async def test_workload_member_fetch_error_is_best_effort(monkeypatch):
    monkeypatch.setattr(settings, "asana_team_member_gids", "minda, ivy")

    async def _users():
        return [{"gid": "minda", "name": "Minda"}, {"gid": "ivy", "name": "Ivy"}]

    async def _member_tasks(gid):
        if gid == "ivy":
            raise RuntimeError("asana 500")
        return [{"due_on": "2026-07-09"}]

    monkeypatch.setattr(asana_service, "list_workspace_users", _users)
    monkeypatch.setattr(asana_service, "list_member_open_tasks", _member_tasks)

    report = await asana_workload.build_team_workload()
    # Ivy's failure → 0 tasks, not a crashed report.
    names = {m["name"]: m["open_count"] for m in report["members"]}
    assert names == {"Minda": 1, "Ivy": 0}
