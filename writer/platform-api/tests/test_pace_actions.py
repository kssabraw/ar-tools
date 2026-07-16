"""Tests for the PACE action layer (Phase 2).

Pure helpers + the stage functions (permission gating, target resolution,
actor-bound requester, previous-status restore) with the small DB reads
monkeypatched. `run` execution is a thin task_service call, exercised via a
monkeypatched update_task.
"""

from __future__ import annotations

import pytest

from services import pace_actions as A
from services import pace_auth, task_service
from services.pace_auth import ActionContext

STATUSES = [
    {"key": "not_started", "category": "not_started", "active": True},
    {"key": "in_progress", "category": "in_progress", "active": True},
    {"key": "blocked", "category": "blocked", "active": True},
    {"key": "complete", "category": "done", "is_done": True, "active": True},
]


def _staff():
    return ActionContext(profile_id="p_staff", role="staff", source="web")


def _va():
    return ActionContext(profile_id="p_va", role="team_member", source="web")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_previous_status_from_activity():
    acts = [
        {"kind": "created", "created_at": "2026-07-01"},
        {"kind": "status_changed", "detail": {"from": "not_started", "to": "in_progress"}, "created_at": "2026-07-02"},
        {"kind": "status_changed", "detail": {"from": "in_progress", "to": "blocked"}, "created_at": "2026-07-05"},
    ]
    # The status before blocked is in_progress (from the into-blocked record),
    # NOT the current status (blocked).
    assert A.previous_status_from_activity(acts, "blocked") == "in_progress"
    # No into-blocked record → None (caller asks).
    assert A.previous_status_from_activity(acts[:1], "blocked") is None


def test_build_nudge_mention():
    assert A.build_nudge_mention("U123") == "<@U123>"
    assert A.build_nudge_mention(None) is None


# ---------------------------------------------------------------------------
# run_nudge — DM-first delivery with channel / in-app fallbacks
# ---------------------------------------------------------------------------
_NUDGE_ARGS = {"assignee_gid": "g1", "assignee_name": "Ivy", "task_name": "GBP audit", "task_id": "t1"}


async def test_run_nudge_dms_the_individual(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_slack_id", lambda gid: "U9")
    monkeypatch.setattr(A.settings, "pace_nudge_via_dm", True)
    monkeypatch.setattr(A.settings, "slack_bot_token", "xoxb-test")
    sent = {}

    async def _post(channel, text):
        sent.update(channel=channel, text=text)

    emits = []
    monkeypatch.setattr("services.slack_assistant.post_message", _post)
    monkeypatch.setattr("services.notifications.emit", lambda **k: emits.append(k) or "nid")
    out = await A.run_nudge(_staff(), "c1", dict(_NUDGE_ARGS))
    assert sent["channel"] == "U9" and "GBP audit" in sent["text"]     # DM'd the user id
    assert out == "✅ Nudge sent — DM'd Ivy directly."
    # In-app copy written; the shared-channel Slack copy suppressed (no double-post).
    assert emits and emits[0]["payload"]["skip_channels"] == ["slack"]


async def test_run_nudge_falls_back_to_channel_on_missing_scope(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_slack_id", lambda gid: "U9")
    monkeypatch.setattr(A.settings, "pace_nudge_via_dm", True)
    monkeypatch.setattr(A.settings, "slack_bot_token", "xoxb-test")

    async def _post(channel, text):
        raise RuntimeError("slack_error: missing_scope")

    emits = []
    monkeypatch.setattr("services.slack_assistant.post_message", _post)
    monkeypatch.setattr("services.notifications.emit", lambda **k: emits.append(k) or "nid")
    out = await A.run_nudge(_staff(), "c1", dict(_NUDGE_ARGS))
    assert "pinged Ivy in the channel" in out
    assert A._dm_scope_broken is True                                  # stop retrying DMs this process
    assert "skip_channels" not in emits[0]["payload"]                  # channel copy allowed
    assert emits[0]["summary"].startswith("<@U9> ")                    # @mention leads the line
    A._dm_scope_broken = False                                         # reset for isolation


async def test_run_nudge_unlinked_is_in_app_only(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_slack_id", lambda gid: None)
    emits = []
    monkeypatch.setattr("services.notifications.emit", lambda **k: emits.append(k) or "nid")
    out = await A.run_nudge(_staff(), "c1", dict(_NUDGE_ARGS))
    assert "in-app nudge (Ivy has no Slack link)" in out
    assert emits[0]["summary"].startswith("a reminder")               # no mention token


# ---------------------------------------------------------------------------
# reassign_task — permission + resolution + actor-bound requester
# ---------------------------------------------------------------------------
@pytest.fixture()
def _reassign_env(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "GBP categories", "status_key": "in_progress",
         "assignee_gid": "g_minda", "assignee_name": "Minda", "completed": False},
    ])
    monkeypatch.setattr(A, "_team_members", lambda: [
        {"gid": "g_ivy", "name": "Ivy", "profile_id": None},
        {"gid": "g_minda", "name": "Minda", "profile_id": None},
    ])


def test_reassign_refused_for_va(_reassign_env):
    kind, payload = A.stage_reassign(_va(), "c1", {"task_name": "GBP categories", "assignee": "Ivy"})
    assert kind == "reply" and "staff" in payload


def test_reassign_staged_for_staff(_reassign_env):
    kind, payload = A.stage_reassign(_staff(), "c1", {"task_name": "GBP categories", "assignee": "Ivy"})
    assert kind == "confirm"
    assert payload["assignee_gid"] == "g_ivy" and payload["assignee_name"] == "Ivy"
    assert payload["_requester"] == "p_staff"          # actor-bound
    assert "from Minda to *Ivy*" in payload["_confirm"]


def test_reassign_unknown_assignee_asks(_reassign_env):
    kind, payload = A.stage_reassign(_staff(), "c1", {"task_name": "GBP categories", "assignee": "Nobody"})
    assert kind == "reply" and "Tracked members" in payload


# ---------------------------------------------------------------------------
# unblock_task — restore previous status, else ask
# ---------------------------------------------------------------------------
def test_unblock_restores_previous_status(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "Stuck task", "status_key": "blocked", "completed": False},
    ])
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: STATUSES)
    monkeypatch.setattr(A, "_task_activity", lambda tid: [
        {"kind": "status_changed", "detail": {"from": "in_progress", "to": "blocked"}, "created_at": "2026-07-05"},
    ])
    kind, payload = A.stage_unblock(_staff(), "c1", {"task_name": "Stuck task"})
    assert kind == "confirm" and payload["status_key"] == "in_progress"
    assert payload["_requester"] == "p_staff"


def test_unblock_asks_when_history_unknown(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "Stuck task", "status_key": "blocked", "completed": False},
    ])
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: STATUSES)
    monkeypatch.setattr(A, "_task_activity", lambda tid: [])
    kind, payload = A.stage_unblock(_staff(), "c1", {"task_name": "Stuck task"})
    assert kind == "reply" and "Which status" in payload


def test_unblock_refuses_non_blocked(monkeypatch):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "Active task", "status_key": "in_progress", "completed": False},
    ])
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: STATUSES)
    kind, payload = A.stage_unblock(_staff(), "c1", {"task_name": "Active task"})
    assert kind == "reply" and "isn't blocked" in payload


# ---------------------------------------------------------------------------
# generate_client_month — permission (admin default)
# ---------------------------------------------------------------------------
def test_generate_month_admin_only():
    admin = ActionContext(profile_id="p_admin", role="admin", source="web")
    kind, payload = A.stage_generate_month(admin, "c1", {})
    assert kind == "confirm" and payload["_requester"] == "p_admin"
    # Staff refused by default (config default admin).
    kind2, payload2 = A.stage_generate_month(_staff(), "c1", {})
    assert kind2 == "reply" and "admin" in payload2


# ---------------------------------------------------------------------------
# run executes via task_service (actor threaded)
# ---------------------------------------------------------------------------
def test_run_reassign_threads_actor(monkeypatch):
    calls = {}
    monkeypatch.setattr(task_service, "update_task",
                        lambda tid, changes, actor_id=None: calls.update({"tid": tid, "changes": changes, "actor": actor_id}))
    msg = A.run_reassign(_staff(), "c1", {"task_id": "t1", "task_name": "X", "assignee_gid": "g_ivy", "assignee_name": "Ivy"})
    assert calls["tid"] == "t1" and calls["changes"]["assignee_gid"] == "g_ivy" and calls["actor"] == "p_staff"
    assert "Ivy" in msg
