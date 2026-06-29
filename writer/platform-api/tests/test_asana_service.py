"""Unit tests for the Asana integration pure helpers (no network).

docs/modules/asana-task-integration-plan-v1_0.md.
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
# month_label / shift_months / is_month_label
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


def test_is_month_label():
    assert asana.is_month_label("July 2026") is True
    assert asana.is_month_label("december 2026") is True
    assert asana.is_month_label("Untitled section") is False
    assert asana.is_month_label("Template") is False
    assert asana.is_month_label("July") is False
    assert asana.is_month_label("July 26") is False
    assert asana.is_month_label(None) is False


# ---------------------------------------------------------------------------
# section_name_exists / month_insert_anchor_gid
# ---------------------------------------------------------------------------
def test_section_name_exists_case_insensitive():
    sections = [{"name": "May 2026"}, {"name": "June 2026"}]
    assert asana.section_name_exists(sections, "June 2026") is True
    assert asana.section_name_exists(sections, "  june 2026 ") is True
    assert asana.section_name_exists(sections, "July 2026") is False
    assert asana.section_name_exists([{"name": None}], "July 2026") is False


def test_month_insert_anchor_gid_before_first_non_month():
    sections = [
        {"gid": "s1", "name": "May 2026"},
        {"gid": "s2", "name": "June 2026"},
        {"gid": "s3", "name": "Untitled section"},
    ]
    # New month inserts before the backlog (first non-month section).
    assert asana.month_insert_anchor_gid(sections) == "s3"


def test_month_insert_anchor_gid_all_months_appends():
    sections = [{"gid": "s1", "name": "May 2026"}, {"gid": "s2", "name": "June 2026"}]
    assert asana.month_insert_anchor_gid(sections) is None


def test_month_insert_anchor_gid_backlog_first():
    sections = [{"gid": "b", "name": "Backlog"}, {"gid": "s1", "name": "May 2026"}]
    assert asana.month_insert_anchor_gid(sections) == "b"


# ---------------------------------------------------------------------------
# build_task_payload (built from app-defined template values)
# ---------------------------------------------------------------------------
def test_build_task_payload_full():
    payload = asana.build_task_payload(
        "40 Citations", "proj1", "sec_new",
        assignee_gid="minda",
        category_field_gid="f_cat", category_option_gid="opt_gbp",
        status_field_gid="f_status", not_started_option_gid="opt_not_started",
    )
    assert payload["name"] == "40 Citations"
    assert payload["assignee"] == "minda"
    assert payload["projects"] == ["proj1"]
    assert payload["memberships"] == [{"project": "proj1", "section": "sec_new"}]
    assert payload["custom_fields"] == {"f_status": "opt_not_started", "f_cat": "opt_gbp"}
    assert "due_on" not in payload  # no due date carried forward


def test_build_task_payload_unassigned_no_custom_fields():
    payload = asana.build_task_payload("Ad-hoc", "proj1", "sec_new")
    assert payload["name"] == "Ad-hoc"
    assert "assignee" not in payload
    assert "custom_fields" not in payload


def test_build_task_payload_status_needs_both_gids():
    # Status field gid present but no option gid → status omitted.
    payload = asana.build_task_payload(
        "x", "proj1", "sec_new",
        status_field_gid="f_status",
        category_field_gid="f_cat", category_option_gid="opt_gbp",
    )
    assert payload["custom_fields"] == {"f_cat": "opt_gbp"}


def test_payload_from_template_row_reads_config(monkeypatch):
    monkeypatch.setattr(settings, "asana_category_field_gid", "f_cat")
    monkeypatch.setattr(settings, "asana_status_field_gid", "f_status")
    monkeypatch.setattr(settings, "asana_status_not_started_option_gid", "opt_ns")
    row = {"name": "GBP Blast", "assignee_gid": "ivy", "category_option_gid": "opt_links"}
    payload = asana.payload_from_template_row(row, "proj1", "sec_new")
    assert payload["name"] == "GBP Blast"
    assert payload["assignee"] == "ivy"
    assert payload["custom_fields"] == {"f_status": "opt_ns", "f_cat": "opt_links"}


# ---------------------------------------------------------------------------
# Workload aggregation
# ---------------------------------------------------------------------------
def test_aggregate_member_workload_counts_and_flags():
    tasks = [
        {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"},
        {"due_on": "2026-07-13"}, {"due_on": None},
    ]
    summary = asana.aggregate_member_workload(
        "minda", "Minda", tasks, max_open=4, max_due_same_day=2,
    )
    assert summary["open_count"] == 5
    assert summary["due_by_day"] == {"2026-07-09": 3, "2026-07-13": 1}
    assert summary["worst_same_day"] == {"date": "2026-07-09", "count": 3}
    assert summary["overloaded"] is True
    assert any("open tasks" in f for f in summary["flags"])
    assert any("2026-07-09" in f for f in summary["flags"])


def test_aggregate_member_workload_not_overloaded():
    summary = asana.aggregate_member_workload(
        "ivy", "Ivy", [{"due_on": "2026-07-06"}], max_open=25, max_due_same_day=4,
    )
    assert summary["overloaded"] is False
    assert summary["flags"] == []


def test_build_workload_report_sorts_and_filters():
    members = [
        {"gid": "ivy", "name": "Ivy", "tasks": [{"due_on": "2026-07-06"}]},
        {"gid": "minda", "name": "Minda", "tasks": [
            {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"}, {"due_on": "2026-07-09"},
        ]},
    ]
    report = asana.build_workload_report(members, max_open=100, max_due_same_day=2)
    assert [m["name"] for m in report["members"]] == ["Minda", "Ivy"]
    assert [m["name"] for m in report["overloaded"]] == ["Minda"]
    assert report["thresholds"] == {"max_open": 100, "max_due_same_day": 2}
