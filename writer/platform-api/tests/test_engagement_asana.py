"""Unit tests for services.engagement_asana — pure payload/notes/section helpers
and the push flow's skip/degrade behaviour (Asana I/O mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from services import engagement_asana as ea


# ── compose_notes ─────────────────────────────────────────────────────────────
def test_compose_notes_carries_rationale_meta_and_deep_link():
    notes = ea.compose_notes({
        "rationale": "Striking distance: position 8 for 'roof repair sydney'.",
        "module": "organic", "category": "onpage", "kind": "quick_win",
        "deep_link": "https://app/clients/1/rankings",
    })
    assert "Striking distance" in notes
    assert "organic · onpage · quick_win" in notes
    assert "https://app/clients/1/rankings" in notes
    assert "SerMaStr" in notes


def test_compose_notes_minimal_action_still_tagged():
    notes = ea.compose_notes({"title": "x"})
    assert "SerMaStr" in notes  # provenance always present


# ── build_action_task_payload ─────────────────────────────────────────────────
def test_payload_sets_name_project_section_assignee_and_status():
    action = {"title": "Reoptimize hot-water page", "rationale": "r",
              "module": "organic", "category": "page"}
    payload = ea.build_action_task_payload(
        action, "PROJ", section_gid="SEC", assignee_gid="USER",
        fields={"status_field_gid": "SF", "not_started_option_gid": "NS"},
    )
    assert payload["name"] == "Reoptimize hot-water page"
    assert payload["projects"] == ["PROJ"]
    assert payload["memberships"] == [{"project": "PROJ", "section": "SEC"}]
    assert payload["assignee"] == "USER"
    assert payload["custom_fields"] == {"SF": "NS"}
    assert "SerMaStr" in payload["notes"]


def test_payload_without_section_or_assignee_omits_them():
    payload = ea.build_action_task_payload({"title": "t"}, "PROJ")
    assert "memberships" not in payload
    assert "assignee" not in payload
    assert "custom_fields" not in payload  # no status field gids resolved
    assert payload["name"] == "t"


def test_payload_falls_back_to_default_name():
    payload = ea.build_action_task_payload({}, "PROJ")
    assert payload["name"] == "SerMaStr action"


# ── current_month_section_gid ─────────────────────────────────────────────────
def test_current_month_section_match_is_case_insensitive():
    sections = [{"gid": "1", "name": "Backlog"}, {"gid": "2", "name": "July 2026"}]
    assert ea.current_month_section_gid(sections, "july 2026") == "2"
    assert ea.current_month_section_gid(sections, "August 2026") is None


# ── push_assigned_actions: skip paths ─────────────────────────────────────────
def test_push_skips_when_asana_not_configured():
    with patch.object(ea.asana_service, "is_configured", return_value=False), \
         patch.object(ea.engagement_executor, "record_event") as rec:
        result = asyncio.run(ea.push_assigned_actions("ENG"))
    assert result["status"] == "skipped"
    assert result["reason"] == "asana_not_configured"
    rec.assert_called_once()


def test_push_skips_when_no_project_mapping():
    with patch.object(ea.asana_service, "is_configured", return_value=True), \
         patch.object(ea.engagement_service, "get_engagement",
                      return_value={"client_id": "C1"}), \
         patch.object(ea, "get_project_gid", return_value=None), \
         patch.object(ea.engagement_executor, "record_event") as rec:
        result = asyncio.run(ea.push_assigned_actions("ENG"))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_project_mapping"
    rec.assert_called_once()
