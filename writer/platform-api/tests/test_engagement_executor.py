"""Unit tests for services.engagement_executor — pure approval/lifecycle helpers."""

from __future__ import annotations

from services import engagement_executor as ee


def test_on_approve_status_routes_auto_to_queued_assigned_to_assigned():
    assert ee.on_approve_status("auto") == "queued"
    assert ee.on_approve_status("assigned") == "assigned"


def test_action_statuses_cover_the_lifecycle():
    # The lifecycle the UI / API can drive an action through.
    for s in ("queued", "in_progress", "assigned", "done", "blocked", "skipped"):
        assert s in ee.ACTION_STATUSES
    assert "bogus" not in ee.ACTION_STATUSES
