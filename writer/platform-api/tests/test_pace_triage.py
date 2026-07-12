"""Tests for PACE v1.4 autonomous triage (§4.10) + the triage_task action.

Pure helpers (month-end parsing, library matching, gap-fill updates) and the
stage function's fill-gaps-only guard.
"""

from __future__ import annotations

from services import pace_triage as T
from services import pace_actions as A
from services.pace_auth import ActionContext

LIBRARY = {
    "blog post": {"name": "Blog Post", "default_hours": 3, "default_category_name": "Content"},
    "citation cleanup": {"name": "Citation Cleanup", "default_hours": 1.5,
                         "default_category_name": "Link Building"},
}
CATS = {"content": "content", "link building": "link_building"}


# ---------------------------------------------------------------------------
# month_end_from_label
# ---------------------------------------------------------------------------
def test_month_end_from_label():
    assert T.month_end_from_label("July 2026") == "2026-07-31"
    assert T.month_end_from_label("February 2028") == "2028-02-29"  # leap year
    assert T.month_end_from_label("Backlog") is None
    assert T.month_end_from_label(None) is None


# ---------------------------------------------------------------------------
# library_match
# ---------------------------------------------------------------------------
def test_library_match_prefers_recorded_name():
    t = {"library_task_name": "Blog Post", "name": "Citation Cleanup"}
    assert T.library_match(t, LIBRARY)["name"] == "Blog Post"
    # Falls back to an exact casefold name match.
    t2 = {"library_task_name": None, "name": "citation cleanup"}
    assert T.library_match(t2, LIBRARY)["name"] == "Citation Cleanup"
    # A near-miss never matches (no guessing).
    assert T.library_match({"name": "Citation Cleanup for Acme"}, LIBRARY) is None


# ---------------------------------------------------------------------------
# build_triage_updates — gaps only, library data only
# ---------------------------------------------------------------------------
def test_updates_fill_all_gaps():
    task = {"name": "Blog Post", "due_date": None, "category": None, "est_hours": None}
    u = T.build_triage_updates(task, LIBRARY, CATS, "July 2026")
    assert u == {"due_date": "2026-07-31", "category": "content", "est_hours": 3}


def test_updates_never_overwrite():
    task = {"name": "Blog Post", "due_date": "2026-07-20", "category": "strategy", "est_hours": 5}
    assert T.build_triage_updates(task, LIBRARY, CATS, "July 2026") == {}


def test_non_library_task_gets_due_only():
    task = {"name": "Weird one-off", "due_date": None, "category": None, "est_hours": None}
    u = T.build_triage_updates(task, LIBRARY, CATS, "July 2026")
    assert u == {"due_date": "2026-07-31"}  # no guessed category/estimate


def test_non_month_section_gets_no_due():
    task = {"name": "Weird one-off", "due_date": None, "category": None, "est_hours": None}
    assert T.build_triage_updates(task, LIBRARY, CATS, "Backlog") == {}


def test_unknown_category_label_skipped():
    lib = {"odd": {"name": "Odd", "default_hours": 2, "default_category_name": "Mystery"}}
    task = {"name": "Odd", "due_date": "2026-07-20", "category": None, "est_hours": None}
    u = T.build_triage_updates(task, lib, CATS, None)
    assert u == {"est_hours": 2}  # estimate fills; unmapped category never guessed


# ---------------------------------------------------------------------------
# stage_triage — fill-gaps-only enforced at the action layer too
# ---------------------------------------------------------------------------
def test_stage_triage_gap_guard(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "Blog Post", "status_key": "not_started",
         "due_date": "2026-07-20", "category": None, "est_hours": None, "completed": False},
    ])
    staff = ActionContext(profile_id="p1", role="staff", source="slack")
    # due_date arrives but the task already has one → only category/est staged.
    kind, payload = A.stage_triage(staff, "c1", {
        "task_name": "Blog Post", "due_date": "2026-07-31", "category": "content", "est_hours": 3,
    })
    assert kind == "confirm"
    assert payload["updates"] == {"category": "content", "est_hours": 3}
    assert "category *content*" in payload["_confirm"] and "due" not in payload["_confirm"]


def test_stage_triage_nothing_to_set(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "Blog Post", "status_key": "not_started",
         "due_date": "2026-07-20", "category": "content", "est_hours": 3, "completed": False},
    ])
    staff = ActionContext(profile_id="p1", role="staff", source="slack")
    kind, payload = A.stage_triage(staff, "c1", {"task_name": "Blog Post", "category": "content"})
    assert kind == "reply" and "already triaged" in payload


def test_triage_reason():
    assert T.triage_reason("X", {"due_date": "2026-07-31", "est_hours": 2}) == \
        "Triage “X” — set due 2026-07-31, est 2h"
