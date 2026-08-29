"""Unit tests for the Everhour integration pure helpers + verify_api_key
(no live network — the I/O methods are mocked).

docs/modules/everhour-time-tracking-integration-plan-v1_0.md.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx

from config import settings
from services import everhour_service as everhour


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------
def test_is_configured_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "everhour_api_key", "")
    assert everhour.is_configured() is False
    monkeypatch.setattr(settings, "everhour_api_key", "sk_test_123")
    assert everhour.is_configured() is True


# ---------------------------------------------------------------------------
# seconds_to_hours
# ---------------------------------------------------------------------------
def test_seconds_to_hours():
    assert everhour.seconds_to_hours(3600) == 1.0
    assert everhour.seconds_to_hours(1800) == 0.5
    assert everhour.seconds_to_hours(0) == 0.0
    assert everhour.seconds_to_hours(None) is None
    assert everhour.seconds_to_hours(5410) == 1.5  # rounds to 2dp


# ---------------------------------------------------------------------------
# build_task_payload — the metadata-only mirror (decision #6)
# ---------------------------------------------------------------------------
def test_build_task_payload_name_only():
    assert everhour.build_task_payload("Blog: roof repair") == {"name": "Blog: roof repair"}


def test_build_task_payload_with_assignee():
    payload = everhour.build_task_payload("40 Citations", assignee_user_id=1304)
    assert payload == {"name": "40 Citations", "assignees": [{"userId": 1304}]}


def test_build_task_payload_never_carries_status_or_due_date():
    # The mirror is metadata-only — status/due-date/section are deliberately
    # not parameters at all, so there's no way to accidentally set them.
    payload = everhour.build_task_payload("Task", assignee_user_id=1, description="notes")
    assert set(payload.keys()) <= {"name", "assignees", "description"}


def test_build_task_payload_blank_name():
    assert everhour.build_task_payload(None) == {"name": ""}


# ---------------------------------------------------------------------------
# parse_user / parse_project
# ---------------------------------------------------------------------------
def test_parse_user():
    raw = {"id": 1304, "name": "Jane Doe", "role": "member", "status": "active", "capacity": 108000}
    assert everhour.parse_user(raw) == {
        "everhour_user_id": "1304",
        "name": "Jane Doe",
        "role": "member",
        "status": "active",
        "capacity_seconds": 108000,
    }


def test_parse_user_missing_id():
    assert everhour.parse_user({"name": "No Id"})["everhour_user_id"] is None


def test_parse_project():
    raw = {"id": "ev:1234567890", "name": "Acme Roofing", "type": "board", "users": []}
    assert everhour.parse_project(raw) == {
        "everhour_project_id": "ev:1234567890",
        "name": "Acme Roofing",
    }


# ---------------------------------------------------------------------------
# parse_time_record — the idempotency-key normalization
# ---------------------------------------------------------------------------
def test_parse_time_record_basic():
    raw = {
        "id": 2660155,
        "time": 3600,
        "user": 1304,
        "date": "2026-08-20",
        "task": {"id": "ev:9876543210", "name": "40 Citations", "projects": ["ev:1234567890"]},
        "isLocked": False,
        "isInvoiced": False,
        "comment": "some notes",
    }
    assert everhour.parse_time_record(raw) == {
        "everhour_record_id": "2660155",
        "everhour_task_id": "ev:9876543210",
        "everhour_project_id": "ev:1234567890",  # first of task.projects
        "everhour_user_id": "1304",
        "entry_date": "2026-08-20",
        "seconds": 3600,
        "billable": None,  # billing not requested -> unknown, not False
        "comment": "some notes",
    }


def test_parse_time_record_with_billing():
    raw = {
        "id": 2660156,
        "time": 1800,
        "user": 1543,
        "date": "2026-08-21",
        "task": {"id": "ev:1", "name": "T", "projects": []},
        "billing": {"billable": True, "rate": 10000, "amount": 5000},
    }
    parsed = everhour.parse_time_record(raw)
    assert parsed["billable"] is True


def test_parse_time_record_no_task_ad_hoc():
    # Ad-hoc Everhour time with a deleted/missing task still parses (nullable
    # everhour_task_id on time_entries) — never raises.
    raw = {"id": 1, "time": 60, "user": 1, "date": "2026-08-20"}
    parsed = everhour.parse_time_record(raw)
    assert parsed["everhour_task_id"] is None
    assert parsed["everhour_project_id"] is None  # no task -> no project
    assert parsed["everhour_record_id"] == "1"


# ---------------------------------------------------------------------------
# is_valid_time_record
# ---------------------------------------------------------------------------
def test_is_valid_time_record():
    good = {"everhour_record_id": "1", "entry_date": "2026-08-20", "seconds": 0}
    assert everhour.is_valid_time_record(good) is True

    missing_id = {"everhour_record_id": None, "entry_date": "2026-08-20", "seconds": 60}
    assert everhour.is_valid_time_record(missing_id) is False

    missing_date = {"everhour_record_id": "1", "entry_date": None, "seconds": 60}
    assert everhour.is_valid_time_record(missing_date) is False

    missing_seconds = {"everhour_record_id": "1", "entry_date": "2026-08-20", "seconds": None}
    assert everhour.is_valid_time_record(missing_seconds) is False

    zero_seconds_is_valid = {"everhour_record_id": "1", "entry_date": "2026-08-20", "seconds": 0}
    assert everhour.is_valid_time_record(zero_seconds_is_valid) is True


# ---------------------------------------------------------------------------
# next_page — bare-array pagination (no total-count field)
# ---------------------------------------------------------------------------
def test_next_page_full_page_continues():
    assert everhour.next_page(1, returned_count=10000, limit=10000) == 2


def test_next_page_partial_page_is_last():
    assert everhour.next_page(3, returned_count=42, limit=10000) is None


def test_next_page_empty_page_is_last():
    assert everhour.next_page(1, returned_count=0, limit=10000) is None


def test_next_page_zero_limit_stops_instead_of_looping_forever():
    # A limit of 0 makes `returned_count < limit` false for any non-negative
    # returned_count, so without the guard this would never signal "last
    # page" and a Phase 3 sync loop could paginate forever.
    assert everhour.next_page(1, returned_count=0, limit=0) is None
    assert everhour.next_page(5, returned_count=0, limit=0) is None


def test_next_page_none_limit_stops_instead_of_crashing():
    assert everhour.next_page(1, returned_count=42, limit=None) is None


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------
async def test_get_project_falls_back_to_empty_dict_on_null_body():
    # A 200 response with a literal JSON `null` body (unusual, not forbidden
    # by the spec) must degrade to {}, not None — get_project is typed
    # -> dict and mirrors asana_service.get_project's `or {}` fallback.
    with patch("services.everhour_service._get", new=AsyncMock(return_value=None)):
        assert await everhour.get_project("ev:123") == {}


# ---------------------------------------------------------------------------
# verify_api_key — the one I/O method Phase 0 needs, mocked
# ---------------------------------------------------------------------------
async def test_verify_api_key_false_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "everhour_api_key", "")
    assert await everhour.verify_api_key() is False


async def test_verify_api_key_true_on_success(monkeypatch):
    monkeypatch.setattr(settings, "everhour_api_key", "sk_test_123")
    with patch(
        "services.everhour_service.get_current_user",
        new=AsyncMock(return_value={"id": 1304, "name": "Jane", "role": "admin", "status": "active"}),
    ):
        assert await everhour.verify_api_key() is True


async def test_verify_api_key_false_on_http_error(monkeypatch):
    monkeypatch.setattr(settings, "everhour_api_key", "bad_key")
    request = httpx.Request("GET", "https://api.everhour.com/users/me")
    response = httpx.Response(403, request=request, json={"code": 403, "message": "Access denied"})
    with patch(
        "services.everhour_service.get_current_user",
        new=AsyncMock(side_effect=httpx.HTTPStatusError("403", request=request, response=response)),
    ):
        assert await everhour.verify_api_key() is False


async def test_verify_api_key_false_on_malformed_json(monkeypatch):
    # A 200 response with a non-JSON body (an intermediary proxy's error
    # page, a truncated response) makes resp.json() raise
    # json.JSONDecodeError, which is a ValueError subclass, NOT an
    # httpx.HTTPError subclass — verify_api_key's docstring promises "never
    # raises", so this must be caught too, not just HTTP-level errors.
    monkeypatch.setattr(settings, "everhour_api_key", "sk_test")
    with patch(
        "services.everhour_service.get_current_user",
        new=AsyncMock(side_effect=json.JSONDecodeError("Expecting value", "<html>", 0)),
    ):
        assert await everhour.verify_api_key() is False


async def test_verify_api_key_false_on_network_error(monkeypatch):
    # A transport-level failure (timeout/DNS/connection-refused) is an
    # httpx.RequestError, a sibling of HTTPStatusError under httpx.HTTPError
    # — confirm the same except clause actually covers it too, not just the
    # status-error case above.
    monkeypatch.setattr(settings, "everhour_api_key", "sk_test")
    with patch(
        "services.everhour_service.get_current_user",
        new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
    ):
        assert await everhour.verify_api_key() is False
