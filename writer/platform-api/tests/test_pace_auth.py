"""Tests for the PACE identity & authorization model (Phase 1).

Pure matrix + confirmation logic. The one DB read (resolve_slack_actor) is
covered by monkeypatching the Supabase client.
"""

from __future__ import annotations

import pytest

from config import settings
from services import pace_auth
from services.pace_auth import ActionContext


def _ctx(role, profile_id="p1", source="web", slack=None):
    return ActionContext(profile_id=profile_id, role=role, source=source, slack_user_id=slack)


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------
def test_min_role_static_and_policy(monkeypatch):
    assert pace_auth.min_role_for("reassign_task") == "staff"
    assert pace_auth.min_role_for("update_own_status") == "team_member"
    # Unknown action fails safe to staff.
    assert pace_auth.min_role_for("some_new_write") == "staff"
    # Policy cells read config live.
    monkeypatch.setattr(settings, "pace_perm_read_board_min_role", "team_member")
    monkeypatch.setattr(settings, "pace_perm_generate_month_min_role", "admin")
    assert pace_auth.min_role_for("read_board") == "team_member"
    assert pace_auth.min_role_for("generate_client_month") == "admin"


def test_can_by_role():
    va, lead, admin = _ctx("team_member"), _ctx("staff"), _ctx("admin")
    # VA can update own status but not reassign / generate month.
    assert pace_auth.can(va, "update_own_status") is True
    assert pace_auth.can(va, "reassign_task") is False
    assert pace_auth.can(va, "generate_client_month") is False
    # Lead can reassign / unblock but not generate month (admin default).
    assert pace_auth.can(lead, "reassign_task") is True
    assert pace_auth.can(lead, "unblock_task") is True
    assert pace_auth.can(lead, "generate_client_month") is False
    # Admin can do everything.
    assert pace_auth.can(admin, "generate_client_month") is True


def test_generate_month_policy_loosen_to_staff(monkeypatch):
    monkeypatch.setattr(settings, "pace_perm_generate_month_min_role", "staff")
    assert pace_auth.can(_ctx("staff"), "generate_client_month") is True


def test_anonymous_and_system():
    anon = ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1")
    assert anon.is_anonymous is True
    assert pace_auth.can(anon, "read_board") is False       # unmapped slack → no writes/gated reads
    assert pace_auth.can(pace_auth.SYSTEM_CONTEXT, "generate_client_month") is True


def test_require_reasons():
    ok, reason = pace_auth.require(_ctx("admin"), "reassign_task")
    assert ok and reason is None
    ok, reason = pace_auth.require(_ctx("team_member"), "reassign_task")
    assert not ok and "staff" in reason
    ok, reason = pace_auth.require(
        ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1"), "reassign_task"
    )
    assert not ok and "Link your Slack account" in reason


# ---------------------------------------------------------------------------
# Actor-bound confirmation
# ---------------------------------------------------------------------------
def test_confirm_actor_binding():
    requester = "p1"
    same = _ctx("staff", profile_id="p1")
    other = _ctx("staff", profile_id="p2")
    admin_other = _ctx("admin", profile_id="p9")
    # Same person → ok.
    assert pace_auth.confirm_actor_ok(requester, same) is True
    # Different non-admin → refused (the VA-replies-yes hole is closed).
    assert pace_auth.confirm_actor_ok(requester, other) is False
    # Admin takeover → ok.
    assert pace_auth.confirm_actor_ok(requester, admin_other) is True
    # No requester recorded → only admin may confirm.
    assert pace_auth.confirm_actor_ok(None, other) is False
    assert pace_auth.confirm_actor_ok(None, admin_other) is True


# ---------------------------------------------------------------------------
# PACE PM designation (owner ruling 2026-09-01)
# ---------------------------------------------------------------------------
def test_pace_pm_from_pure():
    # Admin ⇒ always a PM; otherwise the explicit flag decides.
    assert pace_auth.pace_pm_from("admin", False) is True
    assert pace_auth.pace_pm_from("staff", True) is True
    assert pace_auth.pace_pm_from("staff", False) is False
    assert pace_auth.pace_pm_from("team_member", True) is True
    assert pace_auth.pace_pm_from(None, False) is False


def _stub_supabase(monkeypatch, flag):
    """Patch pace_auth.get_supabase to return one profile row with is_pace_pm=flag."""
    class _Resp:
        def __init__(self, data): self.data = data

    class _Q:
        def __init__(self, data): self._data = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Resp(self._data)

    class _SB:
        def __init__(self, data): self._data = data
        def table(self, *a, **k): return _Q(self._data)

    rows = [{"is_pace_pm": flag}] if flag is not None else []
    monkeypatch.setattr(pace_auth, "get_supabase", lambda: _SB(rows))


def test_is_pace_pm_admin_no_db(monkeypatch):
    # An admin is a PM without any DB read (guard against a lookup).
    def _boom(): raise AssertionError("should not query the DB for an admin")
    monkeypatch.setattr(pace_auth, "get_supabase", _boom)
    assert pace_auth.is_pace_pm(_ctx("admin")) is True


def test_is_pace_pm_system_and_anonymous(monkeypatch):
    monkeypatch.setattr(pace_auth, "get_supabase", lambda: (_ for _ in ()).throw(AssertionError()))
    assert pace_auth.is_pace_pm(pace_auth.SYSTEM_CONTEXT) is True
    anon = ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1")
    assert pace_auth.is_pace_pm(anon) is False


def test_is_pace_pm_staff_flag(monkeypatch):
    # Flagged staff (Minda) ⇒ PM; unflagged staff (Ivy) ⇒ not.
    _stub_supabase(monkeypatch, True)
    assert pace_auth.is_pace_pm(_ctx("staff")) is True
    _stub_supabase(monkeypatch, False)
    assert pace_auth.is_pace_pm(_ctx("staff")) is False


def test_is_pace_pm_fails_closed_on_db_error(monkeypatch):
    def _boom(): raise RuntimeError("db down")
    monkeypatch.setattr(pace_auth, "get_supabase", _boom)
    assert pace_auth.is_pace_pm(_ctx("staff")) is False


def test_require_pace_pm_reasons(monkeypatch):
    _stub_supabase(monkeypatch, True)
    ok, reason = pace_auth.require_pace_pm(_ctx("staff"))
    assert ok and reason is None
    _stub_supabase(monkeypatch, False)
    ok, reason = pace_auth.require_pace_pm(_ctx("staff"))
    assert not ok and "PACE PM" in reason
    ok, reason = pace_auth.require_pace_pm(
        ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1")
    )
    assert not ok and "Link your Slack account" in reason


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------
def test_context_from_auth():
    ctx = pace_auth.context_from_auth({"user_id": "u1", "role": "staff"})
    assert ctx.profile_id == "u1" and ctx.role == "staff" and ctx.source == "web"


def test_resolve_slack_actor(monkeypatch):
    class _Resp:
        def __init__(self, data): self.data = data

    class _Q:
        def __init__(self, data): self._data = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Resp(self._data)

    class _SB:
        def __init__(self, data): self._data = data
        def table(self, *a, **k): return _Q(self._data)

    # Mapped → resolves to the profile.
    monkeypatch.setattr(pace_auth, "get_supabase", lambda: _SB([{"id": "p7", "role": "staff"}]))
    ctx = pace_auth.resolve_slack_actor("U7", channel="C1")
    assert ctx.profile_id == "p7" and ctx.role == "staff" and ctx.source == "slack" and ctx.channel == "C1"

    # Unmapped → anonymous slack context.
    monkeypatch.setattr(pace_auth, "get_supabase", lambda: _SB([]))
    anon = pace_auth.resolve_slack_actor("U8")
    assert anon.is_anonymous and anon.slack_user_id == "U8" and anon.source == "slack"

    # Missing id → anonymous, no DB call needed.
    assert pace_auth.resolve_slack_actor(None).is_anonymous
