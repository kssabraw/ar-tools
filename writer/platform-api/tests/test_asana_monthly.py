"""Tests for the Asana monthly section automation orchestration.

Mocks the Asana REST calls + DB lookups; exercises the create/idempotency/skip
branches of generate_month_for_client.
"""

from __future__ import annotations

from datetime import date

import pytest

from config import settings
from services import asana_monthly, asana_service


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "tok")
    monkeypatch.setattr(settings, "asana_workspace_gid", "ws1")
    monkeypatch.setattr(settings, "asana_category_field_gid", "f_cat")
    monkeypatch.setattr(settings, "asana_status_field_gid", "f_status")
    monkeypatch.setattr(settings, "asana_status_not_started_option_gid", "opt_ns")


def _patch_common(monkeypatch, sections, created_calls):
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: "proj1")

    async def _resolve(project_gid):
        # Stub the per-project by-name resolution to the configured GIDs.
        return {
            "status_field_gid": settings.asana_status_field_gid,
            "not_started_option_gid": settings.asana_status_not_started_option_gid,
            "category_field_gid": settings.asana_category_field_gid,
            "effort_field_gid": settings.asana_effort_field_gid,
        }

    monkeypatch.setattr(asana_service, "resolve_project_fields", _resolve)

    async def _list_sections(project_gid):
        return sections

    async def _create_section(project_gid, name, *, insert_before=None):
        return {"gid": "sec_new", "name": name, "insert_before": insert_before}

    async def _create_task(payload):
        created_calls.append(payload)
        return {"gid": f"t{len(created_calls)}"}

    monkeypatch.setattr(asana_service, "list_sections", _list_sections)
    monkeypatch.setattr(asana_service, "create_section", _create_section)
    monkeypatch.setattr(asana_service, "create_task", _create_task)


async def test_generate_creates_section_and_tasks(monkeypatch):
    created: list[dict] = []
    _patch_common(monkeypatch, [{"gid": "s1", "name": "June 2026"}, {"gid": "b", "name": "Untitled section"}], created)
    monkeypatch.setattr(
        asana_monthly, "get_active_templates",
        lambda cid: [
            {"name": "GBP Blast", "assignee_gid": "minda", "category_option_gid": "opt_gbp"},
            {"name": "40 Citations", "assignee_gid": "ivy", "category_option_gid": "opt_gbp"},
        ],
    )
    result = await asana_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "created"
    assert result["section"] == "July 2026"
    assert result["created"] == 2
    # Tasks placed in the new section, assignees + status carried.
    assert created[0]["name"] == "GBP Blast"
    assert created[0]["assignee"] == "minda"
    assert created[0]["memberships"] == [{"project": "proj1", "section": "sec_new"}]
    assert created[0]["custom_fields"] == {"f_status": "opt_ns", "f_cat": "opt_gbp"}


async def test_generate_idempotent_when_section_exists(monkeypatch):
    created: list[dict] = []
    _patch_common(monkeypatch, [{"gid": "s1", "name": "July 2026"}], created)
    monkeypatch.setattr(asana_monthly, "get_active_templates", lambda cid: [{"name": "X"}])
    result = await asana_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "exists"
    assert result["created"] == 0
    assert created == []  # no tasks created on a no-op


async def test_generate_skips_when_no_mapping(monkeypatch):
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: None)
    result = await asana_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_project_mapping"


async def test_generate_skips_when_no_template(monkeypatch):
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: "proj1")
    monkeypatch.setattr(asana_monthly, "get_active_templates", lambda cid: [])
    result = await asana_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_template"


async def test_generate_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "")
    result = await asana_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "skipped"
    assert result["reason"] == "asana_not_configured"
