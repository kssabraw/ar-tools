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
# match_project_fields (resolve fields by name, project-local)
# ---------------------------------------------------------------------------
def _settings_rows():
    return [
        {"custom_field": {"gid": "s", "name": "Status", "resource_subtype": "enum",
                          "enum_options": [{"gid": "ns", "name": "Not Started"}, {"gid": "cm", "name": "Complete"}]}},
        {"custom_field": {"gid": "cat", "name": "Service Type", "resource_subtype": "enum",
                          "enum_options": [{"gid": "o1", "name": "Content"}]}},
        {"custom_field": {"gid": "h", "name": "Hours", "resource_subtype": "number"}},
    ]


_NAMES = dict(status_field_name="Status", not_started_option_name="Not Started",
              category_field_name="Service Type", effort_field_name="Hours")


def test_match_project_fields_resolves_all():
    m = asana.match_project_fields(_settings_rows(), **_NAMES)
    assert m == {"status_field_gid": "s", "not_started_option_gid": "ns",
                 "category_field_gid": "cat", "effort_field_gid": "h"}


def test_match_project_fields_case_insensitive():
    m = asana.match_project_fields(
        _settings_rows(),
        status_field_name="status", not_started_option_name="not started",
        category_field_name="service type", effort_field_name="hours",
    )
    assert m["status_field_gid"] == "s" and m["not_started_option_gid"] == "ns"
    assert m["category_field_gid"] == "cat" and m["effort_field_gid"] == "h"


def test_match_project_fields_misses_return_none():
    # Wrong names + an effort name that points at a non-number field.
    rows = [{"custom_field": {"gid": "x", "name": "Hours", "resource_subtype": "enum"}}]
    m = asana.match_project_fields(
        rows, status_field_name="Nope", not_started_option_name="Not Started",
        category_field_name="Missing", effort_field_name="Hours",
    )
    assert m == {"status_field_gid": None, "not_started_option_gid": None,
                 "category_field_gid": None, "effort_field_gid": None}


def test_match_project_fields_option_name_mismatch():
    rows = [{"custom_field": {"gid": "s", "name": "Status", "resource_subtype": "enum",
                              "enum_options": [{"gid": "done", "name": "Done"}]}}]
    m = asana.match_project_fields(rows, status_field_name="Status",
                                   not_started_option_name="Not Started",
                                   category_field_name="", effort_field_name="")
    assert m["status_field_gid"] == "s"
    assert m["not_started_option_gid"] is None  # no "Not Started" option present


# ---------------------------------------------------------------------------
# distribute_tasks (capacity-aware auto-distribution)
# ---------------------------------------------------------------------------
def test_distribute_no_members_all_none():
    assert asana.distribute_tasks([1.0, 2.0], []) == [None, None]


def test_distribute_gives_more_to_who_has_room():
    members = [{"gid": "a", "remaining": 10.0}, {"gid": "b", "remaining": 5.0}]
    # Three equal 3h tasks → A (more room) gets two, B gets one.
    assert asana.distribute_tasks([3.0, 3.0, 3.0], members) == ["a", "a", "b"]


def test_distribute_heaviest_task_to_most_room_and_preserves_order():
    members = [{"gid": "a", "remaining": 5.0}, {"gid": "b", "remaining": 5.0}]
    # Heaviest-first: the 4h task lands on A (tie→first), the 1h on B.
    # Result is returned in ORIGINAL order: [1h→B, 4h→A].
    assert asana.distribute_tasks([1.0, 4.0], members) == ["b", "a"]


def test_distribute_accounts_for_negative_remaining():
    members = [{"gid": "a", "remaining": -3.0}, {"gid": "b", "remaining": 8.0}]
    assert asana.distribute_tasks([2.0, 2.0], members) == ["b", "b"]


# ---------------------------------------------------------------------------
# Effort extraction + hours-based workload aggregation
# ---------------------------------------------------------------------------
def _task(due, hours=None):
    cf = [{"gid": "f_hrs", "number_value": hours}] if hours is not None else []
    return {"due_on": due, "custom_fields": cf}


def test_extract_number_field_and_task_hours():
    t = _task("2026-07-09", 3)
    assert asana.extract_number_field(t, "f_hrs") == 3.0
    assert asana.extract_number_field(_task("x"), "f_hrs") is None
    assert asana.extract_number_field(t, "") is None
    # task_hours falls back to default when unestimated.
    assert asana.task_hours(t, "f_hrs", 1.0) == 3.0
    assert asana.task_hours(_task("x"), "f_hrs", 1.5) == 1.5


_AGG = dict(effort_field_gid="f_hrs", default_task_hours=1.0, daily_workdays=5, backlog_weeks=2.0)


def test_aggregate_same_day_hours_flag():
    # 3×3h due the same day = 9h; weekly 30 → daily capacity 6h → 9 > 6 flags.
    tasks = [_task("2026-07-09", 3), _task("2026-07-09", 3), _task("2026-07-09", 3)]
    s = asana.aggregate_member_workload("minda", "Minda", tasks, weekly_hours=30, **_AGG)
    assert s["open_hours"] == 9.0
    assert s["worst_same_day"] == {"date": "2026-07-09", "hours": 9.0}
    assert s["daily_capacity"] == 6.0
    assert s["overloaded"] is True
    assert any("due 2026-07-09" in f for f in s["flags"])


def test_aggregate_unestimated_uses_default_and_counts():
    tasks = [_task("2026-07-09", 2), _task("2026-07-09")]  # one unestimated → 1h
    s = asana.aggregate_member_workload("x", "X", tasks, weekly_hours=100, **_AGG)
    assert s["open_hours"] == 3.0
    assert s["unestimated"] == 1
    assert s["overloaded"] is False  # daily cap 20h, 3h fine


def test_aggregate_backlog_flag():
    # 70h open, weekly 30, backlog_weeks 2 → 60h cap → 70 > 60 flags.
    tasks = [_task(None, 10) for _ in range(7)]
    s = asana.aggregate_member_workload("y", "Y", tasks, weekly_hours=30, **_AGG)
    assert s["open_hours"] == 70.0
    assert s["overloaded"] is True
    assert any("open" in f and "weeks" in f for f in s["flags"])


def test_build_workload_report_sorts_by_hours_and_default_capacity():
    members = [
        {"gid": "ivy", "name": "Ivy", "weekly_hours": 40, "tasks": [_task("2026-07-06", 2)]},
        {"gid": "minda", "name": "Minda", "tasks": [_task("2026-07-09", 9)]},  # no weekly → default
    ]
    report = asana.build_workload_report(
        members, default_weekly_hours=30, **_AGG,
    )
    # Sorted by open_hours desc → Minda (9h) first; Minda over default daily cap (6h).
    assert [m["name"] for m in report["members"]] == ["Minda", "Ivy"]
    assert [m["name"] for m in report["overloaded"]] == ["Minda"]
    assert report["thresholds"]["default_weekly_hours"] == 30
