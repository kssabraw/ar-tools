"""Unit tests for services.asana_push — pure key/assignee/notes helpers, plus
the Director of Operations E2 fix (build spec §3.2): _push_task_plan_native
routing an unassigned monthly-plan task through pm_assign.place_task."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import asana_push as ap


def test_task_key_is_stable_per_line():
    assert ap.task_key({"task_type": "das_v2"}, 3) == "3:das_v2"
    assert ap.task_key({}, 0) == "0:task"


def test_primary_assignee_name_handles_chains():
    assert ap.primary_assignee_name("Ivy") == "Ivy"
    assert ap.primary_assignee_name("Minda → Ivy") == "Minda"
    assert ap.primary_assignee_name("Minda / Ivy") == "Minda"
    assert ap.primary_assignee_name(None) is None
    assert ap.primary_assignee_name("  ") is None


def test_match_member_gid_first_name_and_full_name():
    members = [
        {"gid": "g1", "name": "Ivy Santos"},
        {"gid": "g2", "name": "Minda Reyes"},
        {"gid": "g3", "name": "Kyle"},
    ]
    assert ap.match_member_gid("Ivy", members) == "g1"
    assert ap.match_member_gid("minda reyes", members) == "g2"
    assert ap.match_member_gid("Kyle", members) == "g3"
    assert ap.match_member_gid("Elias", members) is None
    assert ap.match_member_gid(None, members) is None


def test_match_member_gid_ambiguous_returns_none():
    members = [{"gid": "g1", "name": "Ivy Santos"}, {"gid": "g2", "name": "Ivy Cruz"}]
    # Two Ivys → don't guess; the task goes unassigned.
    assert ap.match_member_gid("Ivy", members) is None


def test_task_notes_carries_budget_chain_and_link():
    task = {"quantity": 4, "unit_cost": 10.0, "line_cost": 40.0,
            "assignee": "Minda → Ivy", "rationale": "RD deficit vs competitors"}
    notes = ap.task_notes(task, "July 2026", "https://app/clients/c1/task-plan")
    assert "July 2026" in notes
    assert "4 × $10" in notes and "= $40" in notes
    assert "Minda → Ivy" in notes
    assert "RD deficit" in notes
    assert "https://app/clients/c1/task-plan" in notes


def test_task_notes_flags_unstaffed():
    notes = ap.task_notes({"quantity": 1, "unit_cost": 5.0, "assignee": None}, "July 2026", None)
    assert "UNSTAFFED" in notes


def test_proposal_task_name_and_notes():
    proposal = {"title": "Fund a link round", "action": "Order 2× DAS v2",
                "rationale": "6-week episode with no movement", "sop_citation": "LB SOP §4"}
    assert ap.proposal_task_name(proposal) == "[Strategist] Fund a link round"
    notes = ap.proposal_task_notes(proposal, "https://app/clients/c1/action-plan")
    assert "Order 2× DAS v2" in notes
    assert "6-week episode" in notes
    assert "LB SOP §4" in notes
    assert "action-plan" in notes


def _fake_supabase(plan_row: dict, members: list[dict]):
    tables: dict[str, MagicMock] = {}

    def table(name):
        if name not in tables:
            mock = MagicMock()
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.limit.return_value = mock
            mock.update.return_value = mock
            if name == "monthly_task_plans":
                mock.execute.return_value = MagicMock(data=[plan_row])
            elif name == "asana_team_members":
                mock.execute.return_value = MagicMock(data=members)
            tables[name] = mock
        return tables[name]

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


PLAN_ROW = {
    "id": "plan-1",
    "client_id": "c1",
    "plan": {"tasks": [{"label": "GBP posts", "task_type": "gbp_posts", "assignee": None}]},
    "asana_push": {},
}


def test_push_task_plan_native_autoplaces_when_flag_enabled():
    sb = _fake_supabase(PLAN_ROW, [])
    with (
        patch.object(ap, "get_supabase", return_value=sb),
        patch.object(ap.settings, "pace_autoplace_producers", True),
        patch("services.task_monthly.ensure_month_section", return_value={"id": "sec-1"}),
        patch("services.task_service.create_task", return_value={"id": "task-1"}) as create,
        patch("services.pm_assign.place_task") as place,
    ):
        result = ap._push_task_plan_native("c1", "plan-1")

    assert result["status"] == "ok"
    assert result["created"] == 1
    create.assert_called_once()
    # Name-match assignment stays intact — place_task never overwrites it,
    # it only gap-fills when assignee_id is empty (pm_assign.py's own guard).
    place.assert_called_once_with("task-1")


def test_push_task_plan_native_skips_autoplace_when_flag_disabled():
    sb = _fake_supabase(PLAN_ROW, [])
    with (
        patch.object(ap, "get_supabase", return_value=sb),
        patch.object(ap.settings, "pace_autoplace_producers", False),
        patch("services.task_monthly.ensure_month_section", return_value={"id": "sec-1"}),
        patch("services.task_service.create_task", return_value={"id": "task-1"}),
        patch("services.pm_assign.place_task") as place,
    ):
        result = ap._push_task_plan_native("c1", "plan-1")

    assert result["status"] == "ok"
    place.assert_not_called()


def test_push_task_plan_native_autoplace_failure_is_swallowed():
    """A placement failure is best-effort — the push itself must still succeed."""
    sb = _fake_supabase(PLAN_ROW, [])
    with (
        patch.object(ap, "get_supabase", return_value=sb),
        patch.object(ap.settings, "pace_autoplace_producers", True),
        patch("services.task_monthly.ensure_month_section", return_value={"id": "sec-1"}),
        patch("services.task_service.create_task", return_value={"id": "task-1"}),
        patch("services.pm_assign.place_task", side_effect=RuntimeError("boom")),
    ):
        result = ap._push_task_plan_native("c1", "plan-1")

    assert result["status"] == "ok"
    assert result["created"] == 1
