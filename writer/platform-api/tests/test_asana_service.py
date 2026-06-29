"""Unit tests for the Asana integration pure helpers (no network).

Phase 0 of docs/modules/asana-task-integration-plan-v1_0.md.
"""

from __future__ import annotations

from datetime import date

from config import settings
from services import asana_service as asana


# ---------------------------------------------------------------------------
# is_configured / parse_gids
# ---------------------------------------------------------------------------
def test_is_configured_requires_token_and_workspace(monkeypatch):
    monkeypatch.setattr(settings, "asana_token", "")
    monkeypatch.setattr(settings, "asana_workspace_gid", "")
    assert asana.is_configured() is False
    monkeypatch.setattr(settings, "asana_token", "tok")
    assert asana.is_configured() is False  # workspace still missing
    monkeypatch.setattr(settings, "asana_workspace_gid", "123")
    assert asana.is_configured() is True


def test_parse_gids_trims_and_drops_empties():
    assert asana.parse_gids(" 1 , 2 ,, 3 ") == ["1", "2", "3"]
    assert asana.parse_gids("") == []
    assert asana.parse_gids(None) == []


# ---------------------------------------------------------------------------
# month_label / shift_months / section_name_exists
# ---------------------------------------------------------------------------
def test_month_label():
    assert asana.month_label(date(2026, 7, 3)) == "July 2026"
    assert asana.month_label(date(2026, 1, 31)) == "January 2026"
    assert asana.month_label(date(2026, 12, 1)) == "December 2026"


def test_shift_months_forward_back_and_year_rollover():
    assert asana.shift_months(date(2026, 7, 15), 0) == date(2026, 7, 1)
    assert asana.shift_months(date(2026, 7, 15), 1) == date(2026, 8, 1)
    assert asana.shift_months(date(2026, 12, 10), 1) == date(2027, 1, 1)
    assert asana.shift_months(date(2026, 1, 10), -1) == date(2025, 12, 1)


def test_shift_then_label_is_next_month():
    assert asana.month_label(asana.shift_months(date(2026, 6, 29), 1)) == "July 2026"


def test_section_name_exists_case_insensitive():
    sections = [{"name": "May 2026"}, {"name": "June 2026"}, {"name": "Template"}]
    assert asana.section_name_exists(sections, "June 2026") is True
    assert asana.section_name_exists(sections, "  june 2026 ") is True
    assert asana.section_name_exists(sections, "July 2026") is False
    assert asana.section_name_exists([{"name": None}], "July 2026") is False


# ---------------------------------------------------------------------------
# extract_assignee_gid / extract_enum_option_gid
# ---------------------------------------------------------------------------
def test_extract_assignee_gid():
    assert asana.extract_assignee_gid({"assignee": {"gid": "u1"}}) == "u1"
    assert asana.extract_assignee_gid({"assignee": None}) is None
    assert asana.extract_assignee_gid({}) is None


def test_extract_enum_option_gid():
    task = {
        "custom_fields": [
            {"gid": "f_status", "enum_value": {"gid": "opt_done", "name": "Complete"}},
            {"gid": "f_cat", "enum_value": {"gid": "opt_content", "name": "Content"}},
            {"gid": "f_empty", "enum_value": None},
        ]
    }
    assert asana.extract_enum_option_gid(task, "f_cat") == "opt_content"
    assert asana.extract_enum_option_gid(task, "f_status") == "opt_done"
    assert asana.extract_enum_option_gid(task, "f_empty") is None
    assert asana.extract_enum_option_gid(task, "f_missing") is None
    assert asana.extract_enum_option_gid(task, "") is None


# ---------------------------------------------------------------------------
# build_task_payload
# ---------------------------------------------------------------------------
def _template_task():
    return {
        "name": "40 Citations",
        "assignee": {"gid": "minda"},
        "due_on": "2026-06-16",  # should NOT be carried forward
        "custom_fields": [
            {"gid": "f_status", "enum_value": {"gid": "opt_complete", "name": "Complete"}},
            {"gid": "f_cat", "enum_value": {"gid": "opt_gbp", "name": "GBP Automation"}},
        ],
    }


def test_build_task_payload_carries_name_assignee_category_status_no_due():
    payload = asana.build_task_payload(
        _template_task(), "proj1", "sec_new",
        status_field_gid="f_status",
        not_started_option_gid="opt_not_started",
        category_field_gid="f_cat",
    )
    assert payload["name"] == "40 Citations"
    assert payload["assignee"] == "minda"
    assert payload["projects"] == ["proj1"]
    assert payload["memberships"] == [{"project": "proj1", "section": "sec_new"}]
    # Status reset to Not Started, category carried forward.
    assert payload["custom_fields"] == {"f_status": "opt_not_started", "f_cat": "opt_gbp"}
    # Crucially: no due date carried forward (team fills it in).
    assert "due_on" not in payload


def test_build_task_payload_unassigned_and_no_custom_fields():
    payload = asana.build_task_payload(
        {"name": "Ad-hoc"}, "proj1", "sec_new",
    )
    assert payload["name"] == "Ad-hoc"
    assert "assignee" not in payload
    assert "custom_fields" not in payload


def test_build_task_payload_status_only_when_both_gids_present():
    payload = asana.build_task_payload(
        _template_task(), "proj1", "sec_new",
        status_field_gid="f_status",  # but no not_started option gid
        category_field_gid="f_cat",
    )
    # Status omitted (incomplete config), category still carried.
    assert payload["custom_fields"] == {"f_cat": "opt_gbp"}


# ---------------------------------------------------------------------------
# aggregate_member_workload / build_workload_report
# ---------------------------------------------------------------------------
def test_aggregate_member_workload_counts_and_flags():
    tasks = [
        {"name": "a", "due_on": "2026-07-09"},
        {"name": "b", "due_on": "2026-07-09"},
        {"name": "c", "due_on": "2026-07-09"},
        {"name": "d", "due_on": "2026-07-13"},
        {"name": "e", "due_on": None},  # undated
    ]
    summary = asana.aggregate_member_workload(
        "minda", "Minda", tasks, max_open=4, max_due_same_day=2,
    )
    assert summary["open_count"] == 5
    assert summary["due_by_day"] == {"2026-07-09": 3, "2026-07-13": 1}
    assert summary["worst_same_day"] == {"date": "2026-07-09", "count": 3}
    assert summary["overloaded"] is True
    # Both thresholds breached: 5 open > 4, and 3 due same day > 2.
    assert any("open tasks" in f for f in summary["flags"])
    assert any("2026-07-09" in f for f in summary["flags"])


def test_aggregate_member_workload_not_overloaded():
    summary = asana.aggregate_member_workload(
        "ivy", "Ivy", [{"due_on": "2026-07-06"}], max_open=25, max_due_same_day=4,
    )
    assert summary["overloaded"] is False
    assert summary["flags"] == []


def test_build_workload_report_sorts_and_filters_overloaded():
    members = [
        {"gid": "ivy", "name": "Ivy", "tasks": [{"due_on": "2026-07-06"}]},
        {"gid": "minda", "name": "Minda", "tasks": [
            {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"},
        ]},
    ]
    report = asana.build_workload_report(members, max_open=100, max_due_same_day=2)
    # Sorted by open_count desc → Minda first.
    assert [m["name"] for m in report["members"]] == ["Minda", "Ivy"]
    # Only Minda is overloaded (3 due same day > 2).
    assert [m["name"] for m in report["overloaded"]] == ["Minda"]
    assert report["thresholds"] == {"max_open": 100, "max_due_same_day": 2}
