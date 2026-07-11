"""Tests for the PACE conversational persona/router (Phase 3).

Pure routers + tool schemas + the deterministic portfolio/personal-brief text,
plus the actor-bound web confirm path (the risky bit) with the small DB reads
and the action run monkeypatched. The LLM loop itself is not exercised here —
`interpret_pace` is a thin `_one_llm_call` wrapper covered by the slack_assistant
suite; these tests pin the routing + gating + actor-binding around it.
"""

from __future__ import annotations

from services import pace_agent
from services.pace_agent import PACE_ACTIONS
from services.pace_auth import ActionContext


def test_referenced_config_keys_exist():
    """Regression guard: every settings.pace_* the persona/digest touch at
    runtime must be defined on the settings object (a missing key AttributeErrors
    only once pace_enabled is flipped — invisible to the default-off suite)."""
    from config import settings

    for key in ("pace_enabled", "pace_model", "pace_max_tokens", "pace_digest_weekday_only"):
        assert hasattr(settings, key), f"settings.{key} is not defined"
    assert isinstance(settings.pace_model, str) and settings.pace_model
    assert isinstance(settings.pace_max_tokens, int)


def _staff(pid="p_staff"):
    return ActionContext(profile_id=pid, role="staff", source="web")


def _admin(pid="p_admin"):
    return ActionContext(profile_id=pid, role="admin", source="web")


# ---------------------------------------------------------------------------
# Pure routers
# ---------------------------------------------------------------------------
def test_is_pace_message():
    assert pace_agent.is_pace_message("what's stuck on Acme?")
    assert pace_agent.is_pace_message("move the GBP task to Ivy")          # reassign
    assert pace_agent.is_pace_message("who's overloaded this week?")
    assert pace_agent.is_pace_message("generate this month for First Class")
    assert pace_agent.is_pace_message("nudge whoever owns the blocked task")
    # Not PACE-shaped → falls through to SerMaStr.
    assert not pace_agent.is_pace_message("how is the campaign going?")
    assert not pace_agent.is_pace_message("what should we improve for Acme?")
    assert not pace_agent.is_pace_message("")


def test_is_personal_brief():
    assert pace_agent.is_personal_brief("what should I work on today?")
    assert pace_agent.is_personal_brief("what's on my plate?")
    assert pace_agent.is_personal_brief("my tasks today")
    assert not pace_agent.is_personal_brief("what's stuck on Acme?")
    assert not pace_agent.is_personal_brief("")


# ---------------------------------------------------------------------------
# Tool schemas — PACE-only (two-way isolation)
# ---------------------------------------------------------------------------
def test_build_pace_tools_covers_registry():
    tools = pace_agent.build_pace_tools()
    names = {t["name"] for t in tools}
    assert names == set(PACE_ACTIONS)
    reassign = next(t for t in tools if t["name"] == "reassign_task")
    assert reassign["input_schema"]["required"] == ["task_name", "assignee"]
    gen = next(t for t in tools if t["name"] == "generate_client_month")
    assert gen["input_schema"]["required"] == []


# ---------------------------------------------------------------------------
# Deterministic portfolio read
# ---------------------------------------------------------------------------
def test_portfolio_pace_healthy(monkeypatch):
    monkeypatch.setattr(pace_agent.pm_signals, "build_board_digest",
                        lambda cid: {"clients": [{"stale": [], "overdue": [], "month_pace": {"behind": False}}]})
    assert "healthy" in pace_agent._portfolio_pace_text().lower()


def test_portfolio_pace_with_issues(monkeypatch):
    monkeypatch.setattr(pace_agent.pm_signals, "build_board_digest", lambda cid: {"clients": [
        {"stale": [{"id": "t1"}], "overdue": [{"id": "t2"}], "month_pace": {"behind": True}},
        {"stale": [], "overdue": [{"id": "t3"}], "month_pace": {"behind": False}},
    ]})
    text = pace_agent._portfolio_pace_text()
    assert "1 stuck task" in text and "2 overdue" in text and "1 client behind pace" in text


def test_portfolio_pace_digest_failure(monkeypatch):
    def _boom(cid):
        raise RuntimeError("db down")
    monkeypatch.setattr(pace_agent.pm_signals, "build_board_digest", _boom)
    assert "Which client" in pace_agent._portfolio_pace_text()


# ---------------------------------------------------------------------------
# Personal brief — anonymous actor is told to link
# ---------------------------------------------------------------------------
def test_personal_brief_anonymous():
    anon = ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1")
    assert "Link" in pace_agent.personal_brief_text(anon)


# ---------------------------------------------------------------------------
# Web entry — routing, gating, actor-bound confirm
# ---------------------------------------------------------------------------
async def test_web_ignores_non_pace_message():
    # Not a pending token, not PACE-shaped → None (falls through to SerMaStr).
    out = await pace_agent.maybe_handle_web(
        "how is the campaign going?", [], None, None, _staff())
    assert out is None


async def test_web_confirm_actor_binding_refuses_other(monkeypatch):
    ran = {"count": 0}

    async def _run(name, cid, args, ctx):
        ran["count"] += 1
        return "done"

    monkeypatch.setattr(pace_agent, "_run_pace_action", _run)
    token = pace_agent._store_web_pending(
        "reassign_task", {"id": "c1", "name": "Acme"}, {"task_id": "t1"}, requester="p_staff")
    # A different non-admin confirms → refused, action NOT run.
    out = await pace_agent.maybe_handle_web(
        "yes", [], None, token, ActionContext(profile_id="p_other", role="staff", source="web"))
    assert "Only the person who requested" in out["reply"]
    assert ran["count"] == 0


async def test_web_confirm_runs_for_requester(monkeypatch):
    ran = {}

    async def _run(name, cid, args, ctx):
        ran.update({"name": name, "cid": cid, "actor": ctx.profile_id})
        return "Reassigned to Ivy."

    monkeypatch.setattr(pace_agent, "_run_pace_action", _run)
    token = pace_agent._store_web_pending(
        "reassign_task", {"id": "c1", "name": "Acme"}, {"task_id": "t1"}, requester="p_staff")
    out = await pace_agent.maybe_handle_web("yes", [], None, token, _staff())
    assert out["reply"] == "Reassigned to Ivy." and out["client_id"] == "c1"
    assert ran["name"] == "reassign_task" and ran["actor"] == "p_staff"


async def test_web_confirm_admin_takeover(monkeypatch):
    async def _run(name, cid, args, ctx):
        return "ok"
    monkeypatch.setattr(pace_agent, "_run_pace_action", _run)
    token = pace_agent._store_web_pending(
        "generate_client_month", {"id": "c1", "name": "Acme"}, {}, requester="p_staff")
    out = await pace_agent.maybe_handle_web("yes", [], None, token, _admin("p9"))
    assert out["reply"] == "ok"


def test_store_web_pending_evicts(monkeypatch):
    pace_agent._pace_web_pending.clear()
    t = pace_agent._store_web_pending("nudge_assignee", {"id": "c1", "name": "A"}, {}, "p1")
    assert t in pace_agent._pace_web_pending
    assert pace_agent._pace_web_pending[t]["requester"] == "p1"
    pace_agent._pace_web_pending.clear()
