"""Tests for the Asana monthly section automation orchestration.

Mocks the Asana REST calls + DB lookups; exercises the create/idempotency/skip
branches of generate_month_for_client.
"""

from __future__ import annotations

from datetime import date

import pytest

from config import settings
from services import asana_monthly, asana_service, asana_workload


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
    monkeypatch.setattr(asana_monthly, "get_task_library", lambda: {})

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


# ---------------------------------------------------------------------------
# Auto-distribution (capacity-aware)
# ---------------------------------------------------------------------------
async def test_assign_auto_tasks_distributes_by_capacity(monkeypatch):
    monkeypatch.setattr(settings, "asana_auto_distribute_enabled", True)
    monkeypatch.setattr(asana_monthly, "get_eligible_assignees", lambda cid: ["a", "b"])
    monkeypatch.setattr(asana_monthly, "get_member_capacity", lambda gids: {"a": 40.0, "b": 40.0})

    async def _open(gids):
        return {"a": 30.0, "b": 0.0}  # a is nearly full, b is free

    monkeypatch.setattr(asana_workload, "open_hours_for_members", _open)

    templates = [
        {"name": "x", "auto_assign": True, "est_hours": 5},
        {"name": "y", "auto_assign": True, "est_hours": 5},
        {"name": "z", "assignee_gid": "pinned"},  # pinned — untouched
    ]
    n = await asana_monthly.assign_auto_tasks("c1", templates)
    assert n == 2
    # b has far more remaining (40 vs 10) → both auto tasks go to b.
    assert templates[0]["assignee_gid"] == "b"
    assert templates[1]["assignee_gid"] == "b"
    assert templates[2]["assignee_gid"] == "pinned"


async def test_assign_auto_tasks_noop_when_no_eligible(monkeypatch):
    monkeypatch.setattr(asana_monthly, "get_eligible_assignees", lambda cid: [])
    templates = [{"name": "x", "auto_assign": True}]
    n = await asana_monthly.assign_auto_tasks("c1", templates)
    assert n == 0
    assert "assignee_gid" not in templates[0] or templates[0].get("assignee_gid") is None


async def test_assign_auto_tasks_off(monkeypatch):
    monkeypatch.setattr(settings, "asana_auto_distribute_enabled", False)
    templates = [{"name": "x", "auto_assign": True}]
    assert await asana_monthly.assign_auto_tasks("c1", templates) == 0


# ---------------------------------------------------------------------------
# Task Library inheritance
# ---------------------------------------------------------------------------
def test_apply_library_defaults_fills_blanks_only():
    library = {
        "gbp blast": {"name": "GBP Blast", "default_hours": 1.5, "default_category_name": "GBP Authority"},
        "40 citations": {"name": "40 Citations", "default_hours": 4, "default_category_name": "Link Building"},
    }
    category_options = {"gbp authority": "opt_gbp", "link building": "opt_links"}
    templates = [
        {"name": "GBP Blast", "est_hours": None, "category_option_gid": None},      # inherits both
        {"name": "40 Citations", "est_hours": 6, "category_option_gid": "opt_x"},   # overridden — untouched
        {"name": "Ad-hoc", "est_hours": None, "category_option_gid": None},         # not in library
    ]
    applied = asana_monthly.apply_library_defaults(templates, library, category_options)
    assert applied == 1
    assert templates[0]["est_hours"] == 1.5
    assert templates[0]["category_option_gid"] == "opt_gbp"
    # Overridden row keeps its own values.
    assert templates[1]["est_hours"] == 6
    assert templates[1]["category_option_gid"] == "opt_x"
    # Ad-hoc row stays blank.
    assert templates[2]["est_hours"] is None


def test_apply_library_defaults_case_insensitive_and_partial():
    library = {"map embeds": {"name": "Map Embeds", "default_hours": 2, "default_category_name": "Link Building"}}
    # Category name not in this project's options → only hours inherited.
    templates = [{"name": "map embeds", "est_hours": None, "category_option_gid": None}]
    applied = asana_monthly.apply_library_defaults(templates, library, {})
    assert applied == 1
    assert templates[0]["est_hours"] == 2
    assert templates[0]["category_option_gid"] is None
