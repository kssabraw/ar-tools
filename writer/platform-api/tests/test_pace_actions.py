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

# The real seeded workflow for the status-move tests (order == sort order after
# migration 20260712230000: the linear pipeline, then Completed, then the two
# off-workflow exception statuses parked at the end).
WORKFLOW = [
    {"key": "not_started", "label": "Not Started", "category": "not_started", "active": True, "is_initial": True},
    {"key": "in_progress", "label": "In Progress", "category": "in_progress", "active": True},
    {"key": "in_qa", "label": "In QA", "category": "in_progress", "active": True},
    {"key": "sent_to_client", "label": "Sent to Client", "category": "in_progress", "active": True},
    {"key": "client_approved", "label": "Client Approved", "category": "in_progress", "active": True},
    {"key": "complete", "label": "Completed", "category": "done", "is_done": True, "active": True},
    {"key": "blocked", "label": "Blocked", "category": "blocked", "active": True},
    {"key": "in_review", "label": "In Review", "category": "in_progress", "active": True},
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


def test_resolve_status():
    assert A.resolve_status("In Progress", WORKFLOW)["key"] == "in_progress"   # exact label
    assert A.resolve_status("in_qa", WORKFLOW)["key"] == "in_qa"               # exact key
    assert A.resolve_status("qa", WORKFLOW)["key"] == "in_qa"                  # unique substring
    assert A.resolve_status("done", WORKFLOW)["key"] == "complete"            # unique category
    assert A.resolve_status("Completed", WORKFLOW)["key"] == "complete"        # exact label
    assert A.resolve_status("review", WORKFLOW)["key"] == "in_review"          # unique substring
    assert A.resolve_status("client", WORKFLOW) is None      # Sent to Client vs Client Approved
    assert A.resolve_status("in", WORKFLOW) is None                           # ambiguous → None
    assert A.resolve_status("nonsense", WORKFLOW) is None                     # no match → None
    assert A.resolve_status("", WORKFLOW) is None


def test_move_direction():
    assert A.move_direction(WORKFLOW, "in_progress", "in_qa") == "forward to"
    assert A.move_direction(WORKFLOW, "in_qa", "in_progress") == "back to"
    assert A.move_direction(WORKFLOW, "sent_to_client", "complete") == "forward to"  # into done
    assert A.move_direction(WORKFLOW, "complete", "in_progress") == "back to"        # reopen
    assert A.move_direction(WORKFLOW, "in_progress", "in_progress") == "to"
    assert A.move_direction(WORKFLOW, "in_progress", "unknown") == "to"
    # Exception statuses parked after Completed aren't workflow positions —
    # never "forward to Blocked" / "forward to In Review".
    assert A.move_direction(WORKFLOW, "in_progress", "blocked") == "to"
    assert A.move_direction(WORKFLOW, "in_qa", "in_review") == "to"
    assert A.move_direction(WORKFLOW, "in_review", "in_progress") == "to"


# ---------------------------------------------------------------------------
# run_nudge — DM-first delivery with channel / in-app fallbacks
# ---------------------------------------------------------------------------
_NUDGE_ARGS = {"assignee_gid": "g1", "assignee_name": "Ivy", "task_name": "GBP audit", "task_id": "t1"}


async def test_run_nudge_dms_the_individual(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_profile_slack", lambda gid: ("p_ivy", "U9"))
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
    # In-app copy targeted at their bell; shared-channel Slack copy suppressed.
    assert emits and emits[0]["payload"]["skip_channels"] == ["slack"]
    assert emits[0]["recipient_profile_id"] == "p_ivy"


async def test_run_nudge_falls_back_to_channel_on_missing_scope(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_profile_slack", lambda gid: ("p_ivy", "U9"))
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
    assert emits[0]["recipient_profile_id"] == "p_ivy"                 # still hits their bell
    A._dm_scope_broken = False                                         # reset for isolation


async def test_run_nudge_unlinked_is_in_app_only(monkeypatch):
    A._dm_scope_broken = False
    monkeypatch.setattr(A, "_assignee_profile_slack", lambda gid: (None, None))
    emits = []
    monkeypatch.setattr("services.notifications.emit", lambda **k: emits.append(k) or "nid")
    out = await A.run_nudge(_staff(), "c1", dict(_NUDGE_ARGS))
    assert "in-app nudge (Ivy has no Slack link)" in out
    assert emits[0]["summary"].startswith("a reminder")               # no mention token
    assert emits[0]["recipient_profile_id"] is None                   # unlinked → no personal bell


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


# ---------------------------------------------------------------------------
# set_task_status — forward/backward moves, resolution, own-vs-other permission
# ---------------------------------------------------------------------------
def _status_env(monkeypatch, task):
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [task])
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: WORKFLOW)


def test_set_status_forward_staged_for_staff(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: None)
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "In QA"})
    assert kind == "confirm"
    assert payload["status_key"] == "in_qa" and payload["is_done"] is False
    assert payload["was_completed"] is False and payload["_requester"] == "p_staff"
    assert "forward to *In QA*" in payload["_confirm"]


def test_set_status_backward(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "in_qa",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: None)
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "In Progress"})
    assert kind == "confirm" and payload["status_key"] == "in_progress"
    assert "back to *In Progress*" in payload["_confirm"]


def test_set_status_to_done_flags_completion(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "sent_to_client",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: None)
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "Completed"})
    assert kind == "confirm" and payload["is_done"] is True


def test_set_status_already_there(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "In Progress"})
    assert kind == "reply" and "already" in payload


def test_set_status_unknown_lists_options(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "Purple"})
    assert kind == "reply" and "Options:" in payload and "In QA" in payload


def test_set_status_va_can_move_own(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "My task", "status_key": "in_progress",
                              "assignee_gid": "g_va", "completed": False})
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: "g_va")   # actor owns the task
    kind, payload = A.stage_set_status(_va(), "c1", {"task_name": "My task", "status": "In QA"})
    assert kind == "confirm" and payload["status_key"] == "in_qa"


def test_set_status_va_refused_on_others(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "Her task", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: "g_va")   # not the owner
    kind, payload = A.stage_set_status(_va(), "c1", {"task_name": "Her task", "status": "In QA"})
    assert kind == "reply" and "staff" in payload


def test_set_status_resolves_completed_task_for_reopen(monkeypatch):
    # "Move the finished audit back to In Progress" — no OPEN task matches, the
    # completed fallback finds it, and the staged payload carries was_completed
    # so run takes the reopen branch.
    _status_env(monkeypatch, {"id": "t9", "name": "Other task", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_completed_tasks", lambda cid: [
        {"id": "t1", "name": "GBP audit", "status_key": "complete",
         "assignee_gid": "g_minda", "completed": True},
    ])
    monkeypatch.setattr(A, "_actor_member_gid", lambda ctx: None)
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "In Progress"})
    assert kind == "confirm"
    assert payload["was_completed"] is True and payload["is_done"] is False
    assert payload["status_key"] == "in_progress"
    assert "back to *In Progress*" in payload["_confirm"]


def test_set_status_open_ambiguity_never_falls_to_completed(monkeypatch):
    # Two open matches → ask which one; the completed fallback must NOT silently
    # redirect to a completed task of the same name.
    monkeypatch.setattr(A, "_open_tasks", lambda cid: [
        {"id": "t1", "name": "GBP audit — categories", "status_key": "in_progress", "completed": False},
        {"id": "t2", "name": "GBP audit — reviews", "status_key": "in_progress", "completed": False},
    ])
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: WORKFLOW)
    monkeypatch.setattr(A, "_completed_tasks",
                        lambda cid: (_ for _ in ()).throw(AssertionError("fallback must not run")))
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "GBP audit", "status": "In QA"})
    assert kind == "reply" and "matches 2 tasks" in payload


def test_set_status_no_match_anywhere(monkeypatch):
    _status_env(monkeypatch, {"id": "t1", "name": "GBP audit", "status_key": "in_progress",
                              "assignee_gid": "g_minda", "completed": False})
    monkeypatch.setattr(A, "_completed_tasks", lambda cid: [])
    kind, payload = A.stage_set_status(_staff(), "c1", {"task_name": "Nonexistent", "status": "In QA"})
    assert kind == "reply" and "No task matches" in payload


def test_run_set_status_done_completes(monkeypatch):
    calls = {}
    monkeypatch.setattr(task_service, "complete_task",
                        lambda tid, actor_id=None: calls.update({"completed": tid, "actor": actor_id}))
    monkeypatch.setattr(task_service, "get_statuses", lambda active_only=True: WORKFLOW)
    monkeypatch.setattr(task_service, "done_status_key", lambda statuses: "complete")
    monkeypatch.setattr(task_service, "update_task", lambda *a, **k: calls.setdefault("update", (a, k)))
    msg = A.run_set_status(_staff(), "c1", {"task_id": "t1", "task_name": "X", "status_key": "complete",
                                            "status_label": "Completed", "is_done": True, "was_completed": False})
    assert calls["completed"] == "t1" and calls["actor"] == "p_staff"
    assert "update" not in calls          # exact done status == default → no extra write
    assert "Completed" in msg


def test_run_set_status_reopen_clears_completed(monkeypatch):
    calls = {}
    monkeypatch.setattr(task_service, "update_task",
                        lambda tid, changes, actor_id=None: calls.update({"tid": tid, "changes": changes}))
    A.run_set_status(_staff(), "c1", {"task_id": "t1", "task_name": "X", "status_key": "in_progress",
                                      "status_label": "In Progress", "is_done": False, "was_completed": True})
    assert calls["changes"]["completed"] is False and calls["changes"]["status_key"] == "in_progress"


def test_run_set_status_plain_move(monkeypatch):
    calls = {}
    monkeypatch.setattr(task_service, "update_task",
                        lambda tid, changes, actor_id=None: calls.update({"tid": tid, "changes": changes}))
    A.run_set_status(_staff(), "c1", {"task_id": "t1", "task_name": "X", "status_key": "in_qa",
                                      "status_label": "In QA", "is_done": False, "was_completed": False})
    assert calls["changes"] == {"status_key": "in_qa"}


# ---------------------------------------------------------------------------
# write_client_pulse — staff-gated; run returns the generated body
# ---------------------------------------------------------------------------
def test_write_pulse_refused_for_va():
    kind, payload = A.stage_write_pulse(_va(), "c1", {})
    assert kind == "reply" and "staff" in payload


def test_write_pulse_staged_for_staff():
    kind, payload = A.stage_write_pulse(_staff(), "c1", {})
    assert kind == "confirm" and payload["_requester"] == "p_staff"
    assert "client pulse" in payload["_confirm"]


async def test_run_write_pulse_returns_body(monkeypatch):
    monkeypatch.setattr("services.client_pulse.build_pulse", lambda cid: "Hi [First name], great week!")
    msg = await A.run_write_pulse(_staff(), "c1", {})
    assert "Hi [First name], great week!" in msg


async def test_run_write_pulse_handles_empty(monkeypatch):
    monkeypatch.setattr("services.client_pulse.build_pulse", lambda cid: None)
    msg = await A.run_write_pulse(_staff(), "c1", {})
    assert "couldn't build a pulse" in msg
