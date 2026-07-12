"""Tests for the native task manager (Phase 0).

Pure helpers (status/category resolution, activity diffs, library defaults,
workload adaptation, due-sweep selection) + the monthly generation
orchestration with mocked DB helpers — mirrors test_asana_monthly's style.
"""

from __future__ import annotations

from datetime import date

import pytest

from services import task_monthly, task_service, task_workload
from services.asana_service import aggregate_member_workload

# ---------------------------------------------------------------------------
# task_service pure helpers
# ---------------------------------------------------------------------------
STATUSES = [
    {"key": "not_started", "is_initial": True, "is_done": False, "active": True},
    {"key": "in_progress", "is_initial": False, "is_done": False, "active": True},
    {"key": "complete", "is_initial": False, "is_done": True, "active": True},
]


def test_initial_status_key_prefers_is_initial():
    assert task_service.initial_status_key(STATUSES) == "not_started"


def test_initial_status_key_falls_back_to_first_active():
    statuses = [
        {"key": "retired", "is_initial": True, "active": False},
        {"key": "open", "is_initial": False, "active": True},
    ]
    assert task_service.initial_status_key(statuses) == "open"
    assert task_service.initial_status_key([]) is None


def test_done_status_key():
    assert task_service.done_status_key(STATUSES) == "complete"
    assert task_service.done_status_key(STATUSES[:2]) is None


CATEGORIES = [
    {"key": "content", "label": "Content"},
    {"key": "link_building", "label": "Link Building"},
]


def test_resolve_category_key_matches_key_and_label():
    assert task_service.resolve_category_key("content", CATEGORIES) == "content"
    assert task_service.resolve_category_key("Link Building", CATEGORIES) == "link_building"
    assert task_service.resolve_category_key("  LINK BUILDING ", CATEGORIES) == "link_building"


def test_resolve_category_key_passthrough_and_blank():
    # Unknown labels pass through (imported/legacy values aren't lost).
    assert task_service.resolve_category_key("GBP Blast", CATEGORIES) == "GBP Blast"
    assert task_service.resolve_category_key(None, CATEGORIES) is None
    assert task_service.resolve_category_key("   ", CATEGORIES) is None


def test_diff_activity_kinds_and_skips():
    before = {"name": "A", "assignee_gid": None, "status_key": "not_started", "due_date": None}
    changes = {
        "name": "B",                    # renamed
        "assignee_gid": "g1",           # assigned
        "status_key": "not_started",    # unchanged → skipped
        "due_date": "2026-08-01",       # due_changed
        "description": "long text",     # edited, body redacted
    }
    entries = task_service.diff_activity(before, changes)
    kinds = {e["kind"] for e in entries}
    assert kinds == {"renamed", "assigned", "due_changed", "edited"}
    desc = next(e for e in entries if e["kind"] == "edited")
    assert desc["detail"] == {"field": "description"}  # no body leaked
    assigned = next(e for e in entries if e["kind"] == "assigned")
    assert assigned["detail"] == {"field": "assignee_gid", "from": None, "to": "g1"}


# ---------------------------------------------------------------------------
# task_monthly pure helpers
# ---------------------------------------------------------------------------
def test_apply_native_defaults_inherits_blanks_only():
    library = {
        "gbp blast": {"name": "GBP Blast", "default_hours": 1.5, "default_category_name": "GBP Authority"},
    }
    rows = [
        {"name": "GBP Blast", "est_hours": None, "category_name": None},   # inherits both
        {"name": "GBP Blast", "est_hours": 3.0, "category_name": "Content"},  # own values win
        {"name": "Unknown Task", "est_hours": None, "category_name": None},   # no lib match
    ]
    applied = task_monthly.apply_native_defaults(rows, library)
    assert applied == 1
    assert rows[0]["est_hours"] == 1.5 and rows[0]["category_name"] == "GBP Authority"
    assert rows[1]["est_hours"] == 3.0 and rows[1]["category_name"] == "Content"
    assert rows[2]["est_hours"] is None


def test_month_source_ref_stable():
    ref = task_monthly.month_source_ref("c1", date(2026, 7, 15), "row9")
    assert ref == "monthly:c1:2026-07:row9"


# ---------------------------------------------------------------------------
# task_workload: adapter feeds the reused Asana workload math
# ---------------------------------------------------------------------------
def test_adapt_task_row_and_aggregate():
    rows = [
        {"est_hours": 4, "due_date": "2026-07-14"},
        {"est_hours": None, "due_date": "2026-07-14"},  # default hours
        {"est_hours": 2.5, "due_date": None},
    ]
    adapted = [task_workload.adapt_task_row(r) for r in rows]
    summary = aggregate_member_workload(
        "g1", "Ivy", adapted,
        weekly_hours=10.0,
        effort_field_name="est_hours",
        effort_field_gid="",
        default_task_hours=1.0,
        daily_workdays=5,
        backlog_weeks=2.0,
    )
    assert summary["open_hours"] == 7.5           # 4 + 1 (default) + 2.5
    assert summary["unestimated"] == 1
    assert summary["due_hours_by_day"] == {"2026-07-14": 5.0}
    assert summary["overloaded"] is True          # 5h due same day > 10/5=2h/day


async def test_native_workload_alert_silent_when_disabled(monkeypatch):
    from config import settings
    from services import notifications

    monkeypatch.setattr(settings, "workload_overload_alert_enabled", False)
    calls = []
    monkeypatch.setattr(
        task_workload, "build_team_workload",
        lambda: {"overloaded": [{"gid": "g1", "name": "Ivy", "flags": ["9h"]}]},
    )
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: calls.append(1))

    result = await task_workload.run_workload_alert()
    assert result == {"emitted": False, "reason": "alert_disabled"}
    assert calls == []


def test_select_due_tasks_buckets():
    today = date(2026, 7, 11)
    rows = [
        {"assignee_gid": "g1", "assignee_name": "Ivy", "due_date": "2026-07-11", "name": "Due now"},
        {"assignee_gid": "g1", "assignee_name": "Ivy", "due_date": "2026-07-01", "name": "Late"},
        {"assignee_gid": "g2", "assignee_name": "Minda", "due_date": date(2026, 7, 10), "name": "Also late"},
        {"assignee_gid": "g1", "assignee_name": "Ivy", "due_date": "2026-08-01", "name": "Future"},   # skipped
        {"assignee_gid": None, "due_date": "2026-07-01", "name": "Unassigned"},                       # skipped
        {"assignee_gid": "g3", "due_date": None, "name": "Undated"},                                  # skipped
    ]
    buckets = task_workload.select_due_tasks(rows, today)
    assert set(buckets) == {"g1", "g2"}
    assert buckets["g1"]["due_today"] == ["Due now"]
    assert buckets["g1"]["overdue"] == ["Late"]
    assert buckets["g2"]["overdue"] == ["Also late"]


def test_bucket_by_due():
    today = date(2026, 7, 11)
    rows = [
        {"name": "Old", "due_date": "2026-07-01"},
        {"name": "Now", "due_date": "2026-07-11"},
        {"name": "Soon", "due_date": "2026-07-15"},
        {"name": "Edge", "due_date": "2026-07-18"},   # today+7 → this_week
        {"name": "Far", "due_date": "2026-08-11"},
        {"name": "Someday", "due_date": None},
    ]
    buckets = task_service.bucket_by_due(rows, today)
    assert [r["name"] for r in buckets["overdue"]] == ["Old"]
    assert [r["name"] for r in buckets["today"]] == ["Now"]
    assert [r["name"] for r in buckets["this_week"]] == ["Soon", "Edge"]
    assert [r["name"] for r in buckets["later"]] == ["Far"]
    assert [r["name"] for r in buckets["no_date"]] == ["Someday"]


# ---------------------------------------------------------------------------
# task_collab pure helpers (Phase 2)
# ---------------------------------------------------------------------------
def test_parse_mentions_full_and_first_name():
    from services.task_collab import parse_mentions

    candidates = [
        {"id": "u1", "full_name": "Ivy Lane"},
        {"id": "u2", "full_name": "Minda Reyes"},
        {"id": "u3", "full_name": "Kyle"},
    ]
    assert parse_mentions("ping @Ivy Lane and @minda about this", candidates) == ["u1", "u2"]
    assert parse_mentions("@kyle please review", candidates) == ["u3"]
    assert parse_mentions("no mentions here", candidates) == []
    assert parse_mentions("", candidates) == []
    # Repeated mention → deduped; unknown @names ignored.
    assert parse_mentions("@Ivy @ivy @nobody", candidates) == ["u1"]


def test_safe_filename():
    from services.task_collab import safe_filename

    assert safe_filename("report (final).pdf") == "report_final_.pdf"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename(None) == "upload"
    assert len(safe_filename("x" * 500)) == 120


def test_duplicate_task_copies_fields_not_source(monkeypatch):
    from services import task_collab

    original = {
        "id": "t1",
        "name": "GBP Blast",
        "client_id": "c1",
        "section_id": "sec1",
        "description": "desc",
        "assignee_gid": "g1",
        "assignee_name": "Ivy",
        "category": "gbp_authority",
        "due_date": "2026-07-20",
        "start_date": None,
        "est_hours": 1.5,
        "sort_order": 3,
        "library_task_name": "GBP Blast",
        "source": "monthly",
        "source_ref": "monthly:c1:2026-07:r1",
        "subtasks": [{"name": "Step 1"}, {"name": "Step 2"}],
    }
    monkeypatch.setattr(task_service, "get_task_detail", lambda tid: original)
    created = {}

    def _create(name, **kwargs):
        created.update({"name": name, **kwargs})
        return {"id": "t2", "name": name, "client_id": kwargs.get("client_id")}

    sub_calls = []
    monkeypatch.setattr(task_service, "create_task", _create)
    monkeypatch.setattr(
        task_service, "create_subtasks", lambda parent, names, **kw: sub_calls.append(list(names))
    )

    copy = task_collab.duplicate_task("t1", with_subtasks=True, actor_id="u1")
    assert copy["id"] == "t2"
    assert created["name"] == "GBP Blast (copy)"
    assert created["assignee_gid"] == "g1" and created["est_hours"] == 1.5
    # A duplicate is a manual task — the producer key must NOT carry over.
    assert "source" not in created and "source_ref" not in created
    assert sub_calls == [["Step 1", "Step 2"]]


# ---------------------------------------------------------------------------
# Producers (Phase 4) + importer (Phase 5) pure helpers
# ---------------------------------------------------------------------------
def test_action_source_ref_stable_across_rebuilds():
    from services.task_producers import action_source_ref

    a = {"kind": "quick_win", "keyword": "Roof Repair", "recommendation": "Reoptimize the page"}
    b = {"kind": "quick_win", "keyword": "roof repair", "recommendation": "Different wording"}
    assert action_source_ref("c1", a) == action_source_ref("c1", b)  # same item, new build
    assert action_source_ref("c1", a) != action_source_ref("c2", a)  # per-client
    no_kw = {"kind": "consolidate", "cta_label": "Open GSC Research"}
    assert action_source_ref("c1", no_kw) == "c1:consolidate:open gsc research"


def test_import_map_status_variants():
    from services.task_import import map_status

    assert map_status("Not Started", "not_started") == "not_started"
    assert map_status("Sent For Approval", "not_started") == "in_review"
    assert map_status("With Client", "not_started") == "sent_to_client"
    assert map_status("Waiting on URL to Go Live", "not_started") == "client_approved"
    assert map_status("Done", "not_started") == "complete"
    assert map_status("On Hold", "not_started") == "blocked"
    # Unknown / blank → the initial status.
    assert map_status("Some Custom State", "not_started") == "not_started"
    assert map_status(None, "not_started") == "not_started"


def test_import_field_and_section_helpers():
    from services.task_import import extract_enum_field, month_period, section_name_of

    task = {
        "custom_fields": [
            {"name": "Status", "enum_value": {"name": "In Progress"}},
            {"name": "Service Type", "enum_value": None, "display_value": "Link Building"},
        ],
        "memberships": [
            {"project": {"gid": "other"}, "section": {"name": "Backlog"}},
            {"project": {"gid": "proj1"}, "section": {"name": "July 2026"}},
        ],
    }
    assert extract_enum_field(task, "Status") == "In Progress"
    assert extract_enum_field(task, "service type") == "Link Building"
    assert extract_enum_field(task, "Missing") is None
    assert section_name_of(task, "proj1") == "July 2026"
    assert month_period("July 2026") == "2026-07-01"
    assert month_period("Backlog") is None


# ---------------------------------------------------------------------------
# Monthly generation orchestration (mocked DB)
# ---------------------------------------------------------------------------
@pytest.fixture()
def _gen_env(monkeypatch):
    """Stub every I/O edge of generate_month_for_client."""
    monkeypatch.setattr(
        task_monthly, "ensure_month_section", lambda cid, target: {"id": "sec1", "name": "July 2026"}
    )
    monkeypatch.setattr(task_monthly, "get_task_library", lambda: {})
    monkeypatch.setattr(task_monthly, "assign_auto_tasks", lambda cid, rows: 0)
    monkeypatch.setattr(
        task_monthly, "get_library_checklists",
        lambda: {"service silo": ["Step 1", "Step 2"]},
    )
    monkeypatch.setattr(task_service, "get_categories", lambda active_only=True: CATEGORIES)
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: STATUSES)

    created_calls = []
    subtask_calls = []

    def _create_task(name, **kwargs):
        created_calls.append({"name": name, **kwargs})
        return {"id": f"t{len(created_calls)}", "name": name, "client_id": kwargs.get("client_id")}

    monkeypatch.setattr(task_service, "create_task", _create_task)
    monkeypatch.setattr(
        task_service, "create_subtasks",
        lambda parent, names, **kw: subtask_calls.append((parent["id"], list(names))) or len(names),
    )
    return created_calls, subtask_calls


def test_generate_month_creates_tasks_with_checklists(monkeypatch, _gen_env):
    created_calls, subtask_calls = _gen_env
    monkeypatch.setattr(
        task_monthly, "get_active_templates",
        lambda cid: [
            {"id": "r1", "name": "Service Silo", "category_name": "Content", "est_hours": 2},
            {"id": "r2", "name": "GBP Posts", "category_name": None, "est_hours": None},
        ],
    )
    result = task_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "created"
    assert result["created"] == 2 and result["existing"] == 0 and result["errors"] == []
    assert result["section"] == "July 2026"

    first = created_calls[0]
    assert first["source"] == "monthly"
    assert first["source_ref"] == "monthly:c1:2026-07:r1"
    assert first["status_key"] == "not_started"
    assert first["category"] == "content"          # label resolved to key
    assert first["section_id"] == "sec1"
    # Only the row matching a library checklist gets subtasks.
    assert subtask_calls == [("t1", ["Step 1", "Step 2"])]


def test_generate_month_skips_existing_and_isolates_errors(monkeypatch, _gen_env):
    created_calls, _ = _gen_env
    monkeypatch.setattr(
        task_monthly, "get_active_templates",
        lambda cid: [
            {"id": "r1", "name": "Already There"},
            {"id": "r2", "name": "Boom"},
            {"id": "r3", "name": "Fresh"},
        ],
    )

    def _create(name, **kwargs):
        if name == "Already There":
            return {"id": "t0", "_existing": True}
        if name == "Boom":
            raise RuntimeError("db down")
        created_calls.append({"name": name, **kwargs})
        return {"id": "t1", "name": name}

    monkeypatch.setattr(task_service, "create_task", _create)
    result = task_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["created"] == 1
    assert result["existing"] == 1
    assert len(result["errors"]) == 1 and result["errors"][0].startswith("Boom")


def test_generate_month_no_template(monkeypatch):
    monkeypatch.setattr(task_monthly, "get_active_templates", lambda cid: [])
    result = task_monthly.generate_month_for_client("c1", date(2026, 7, 1))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_template"
