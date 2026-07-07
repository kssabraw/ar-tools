"""Unit tests for services.asana_push — pure key/assignee/notes helpers."""

from __future__ import annotations

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
