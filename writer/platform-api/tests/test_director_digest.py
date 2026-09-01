"""Unit tests for services.director.digest — the weekly operations-flow
digest (build spec §6.2, owner decision 2): dedupe_key stability across a
re-run, the all-clear suppression, and enumerate-don't-count body formatting."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from services.director import digest as D

MONDAY = date(2026, 8, 24)
FRIDAY = date(2026, 8, 28)


def test_dedupe_key_stable_within_the_same_iso_week():
    assert D.dedupe_key(MONDAY) == D.dedupe_key(FRIDAY) == "ops_digest:2026-W35"


def test_dedupe_key_differs_across_weeks():
    assert D.dedupe_key(FRIDAY) != D.dedupe_key(date(2026, 9, 1))


def test_format_digest_enumerates_named_clients_not_just_counts():
    model = {
        "flow": {"flags": [
            {"seam": "strategist_approved_unplaced", "client_id": "c1", "evidence": {}},
            {"seam": "strategist_approved_unplaced", "client_id": "c2", "evidence": {}},
            {"seam": "qa_idle", "client_id": None, "evidence": {"last_entered_at": None}},
        ]},
        "autonomy": {"executed": 0, "proposed": 0, "escalated": 0},
    }
    names = {"c1": "Acme Roofing", "c2": "WheelHouse IT"}
    body = D.format_digest(model, names)
    assert "Acme Roofing" in body
    assert "WheelHouse IT" in body
    assert "qa_idle" in body


def test_format_digest_surfaces_unwatched_seam_distinctly():
    model = {
        "flow": {"flags": [
            {"seam": "unwatched_seam", "client_id": None,
             "evidence": {"source": "mystery_producer", "open_count": 4}},
        ]},
        "autonomy": {},
    }
    body = D.format_digest(model, {})
    assert "mystery_producer" in body
    assert "4" in body


def test_format_digest_all_clear_message():
    assert D.format_digest({"flow": {"flags": []}, "autonomy": {}}, {}) == (
        "No cross-agent seams flagged this week."
    )


def test_format_digest_renders_audit_health_section():
    model = {
        "flow": {"flags": []},
        "autonomy": {},
        "audit_health": {"findings": [
            {"label": "SerMaStr `link_building` proposals are dismissed 71% of the time"},
            {"label": "PACE `reassign_task` is declined or undone 62% of the time"},
        ]},
    }
    body = D.format_digest(model, {})
    assert "Agent process health:" in body
    assert "link_building" in body and "reassign_task" in body


def test_run_weekly_emits_when_only_audit_health_findings_present():
    model = {
        "flow": {"flags": []},
        "autonomy": {"executed": 0, "proposed": 0, "escalated": 0},
        "audit_health": {"findings": [
            {"label": "SerMaStr logged no proposals in the window"},
        ]},
    }
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", return_value=model),
        patch("services.notifications.emit", return_value="notif-a") as emit,
    ):
        result = D.run_weekly(FRIDAY)
    assert result["emitted"] is True
    emit.assert_called_once()


def test_run_weekly_disabled_no_emit():
    with patch.object(D.settings, "director_enabled", False):
        assert D.run_weekly(FRIDAY) == {"emitted": False, "reason": "disabled"}


def test_run_weekly_suppresses_on_all_clear_week():
    model = {"flow": {"flags": []}, "autonomy": {"executed": 0, "proposed": 0, "escalated": 0}}
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", return_value=model),
    ):
        result = D.run_weekly(FRIDAY)
    assert result == {"emitted": False, "reason": "all_clear"}


def test_run_weekly_emits_when_flags_present():
    model = {
        "flow": {"flags": [
            {"seam": "qa_idle", "client_id": None, "evidence": {"last_entered_at": None}},
        ]},
        "autonomy": {"executed": 0, "proposed": 0, "escalated": 0},
    }
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", return_value=model),
        patch("services.notifications.emit", return_value="notif-1") as emit,
    ):
        result = D.run_weekly(FRIDAY)

    assert result == {"emitted": True, "flags": 1, "deduped": False}
    kwargs = emit.call_args.kwargs
    assert kwargs["client_id"] is None
    assert kwargs["kind"] == "ops_digest"
    assert kwargs["dedupe_key"] == "ops_digest:2026-W35"


def test_run_weekly_emits_when_only_autonomy_activity_present():
    model = {"flow": {"flags": []}, "autonomy": {"executed": 2, "proposed": 1, "escalated": 0}}
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", return_value=model),
        patch("services.notifications.emit", return_value="notif-2") as emit,
    ):
        result = D.run_weekly(FRIDAY)
    assert result["emitted"] is True
    emit.assert_called_once()


def test_run_weekly_deduped_re_run_returns_false_emitted():
    model = {
        "flow": {"flags": [{"seam": "qa_idle", "client_id": None, "evidence": {}}]},
        "autonomy": {"executed": 0, "proposed": 0, "escalated": 0},
    }
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", return_value=model),
        patch("services.notifications.emit", return_value=None),  # dedupe_key conflict → None
    ):
        result = D.run_weekly(FRIDAY)
    assert result == {"emitted": False, "flags": 1, "deduped": True}


def test_run_weekly_never_raises_on_read_model_failure():
    with (
        patch.object(D.settings, "director_enabled", True),
        patch.object(D.read_model, "build_read_model", side_effect=RuntimeError("boom")),
    ):
        result = D.run_weekly(FRIDAY)
    assert result["emitted"] is False
    assert result["reason"] == "error"
