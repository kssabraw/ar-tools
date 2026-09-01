"""Unit tests for the audit-log health notification path in
services.director.reconcile._notify_audit_health (owner ask 2026-09-01).

These process-health findings are NOT board tasks — they emit ops_seam
notifications deduped per ISO week (mirroring qa_idle)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from services.director import reconcile as R

FRIDAY = date(2026, 8, 28)  # ISO 2026-W35


def _model_with_findings():
    return {
        "audit_health": {"findings": [
            {"agent": "sermastr", "kind": "high_dismiss", "client_id": None,
             "ident": "sermastr:high_dismiss:link_building",
             "label": "SerMaStr `link_building` proposals are dismissed 71% of the time",
             "detail": {"decided": 7}, "severity": "warning"},
            {"agent": "pace", "kind": "high_dismiss", "client_id": None,
             "ident": "pace:high_dismiss:reassign_task",
             "label": "PACE `reassign_task` is declined or undone 62% of the time",
             "detail": {"total": 8}, "severity": "warning"},
        ]}
    }


def test_notify_audit_health_emits_one_ops_seam_per_finding():
    with patch("services.notifications.emit", return_value="n") as emit:
        count = R._notify_audit_health(_model_with_findings(), FRIDAY)
    assert count == 2
    assert emit.call_count == 2
    kinds = {c.kwargs["kind"] for c in emit.call_args_list}
    assert kinds == {"ops_seam"}
    # SerMaStr finding deep-links to the strategist log, PACE to the pace log.
    links = {c.kwargs["payload"]["link"] for c in emit.call_args_list}
    assert links == {"/strategist/log", "/pace/log"}


def test_notify_audit_health_dedupe_key_is_per_iso_week():
    with patch("services.notifications.emit", return_value="n") as emit:
        R._notify_audit_health(_model_with_findings(), FRIDAY)
    keys = {c.kwargs["dedupe_key"] for c in emit.call_args_list}
    assert keys == {
        "ops_seam:audit:sermastr:high_dismiss:link_building:2026-W35",
        "ops_seam:audit:pace:high_dismiss:reassign_task:2026-W35",
    }


def test_notify_audit_health_counts_only_non_deduped_emits():
    # emit returns None on a dedupe conflict — those aren't counted as new alerts.
    with patch("services.notifications.emit", side_effect=["n", None]):
        assert R._notify_audit_health(_model_with_findings(), FRIDAY) == 1


def test_notify_audit_health_no_findings_is_a_noop():
    with patch("services.notifications.emit") as emit:
        assert R._notify_audit_health({"audit_health": {"findings": []}}, FRIDAY) == 0
        assert R._notify_audit_health({}, FRIDAY) == 0
    emit.assert_not_called()
