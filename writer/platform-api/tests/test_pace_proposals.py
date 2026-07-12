"""Tests for the PACE v1.4 Chase Plan engine (§4.8).

Pure reply parsing + rendering, the build pipeline (synthetic generators +
monkeypatched PACE_ACTIONS stages), selective confirm with per-item role
authorization, the autonomy fork, and the daily runner's gates/dedupe.
"""

from __future__ import annotations

from datetime import date

import pytest

from config import settings
from services import pace_proposals as P
from services.pace_auth import ActionContext


def _staff(pid="p_staff", role="staff"):
    return ActionContext(profile_id=pid, role=role, source="slack")


# ---------------------------------------------------------------------------
# parse_plan_reply (pure)
# ---------------------------------------------------------------------------
def test_parse_bare_yes_approves_all():
    assert P.parse_plan_reply("yes", 3) == [1, 2, 3]
    assert P.parse_plan_reply("Go ahead", 2) == [1, 2]


def test_parse_selective():
    assert P.parse_plan_reply("yes 1,3", 4) == [1, 3]
    assert P.parse_plan_reply("yes 1, 3", 4) == [1, 3]
    assert P.parse_plan_reply("approve 2", 4) == [2]
    assert P.parse_plan_reply("yes 1-3", 5) == [1, 2, 3]


def test_parse_out_of_range_and_junk():
    assert P.parse_plan_reply("yes 9", 3) is None       # all picks out of range
    assert P.parse_plan_reply("yes 2,9", 3) == [2]      # in-range survives
    # A phrase after "yes" isn't an index list — it's a plain affirmative → all.
    assert P.parse_plan_reply("yes please do it", 3) == [1, 2, 3]


def test_parse_non_approval_leaves_pending():
    assert P.parse_plan_reply("what does item 2 mean?", 3) is None
    assert P.parse_plan_reply("no", 3) is None
    assert P.parse_plan_reply("", 3) is None
    assert P.parse_plan_reply("yes", 0) is None


# ---------------------------------------------------------------------------
# render_plan (pure)
# ---------------------------------------------------------------------------
def test_render_plan():
    plan = {
        "items": [
            {"index": 1, "reason": "Nudge Ivy — “GBP categories” stuck 6 days", "client_name": "IHBS"},
            {"index": 2, "reason": "Place “Location page” → Minda", "client_name": "Acme"},
        ],
        "auto_results": ["Nudge sent — pinged Bo."],
        "flags": ["“Odd task” — couldn't resolve a unique target"],
        "overflow": 3,
    }
    text = P.render_plan(plan)
    assert "2 proposed actions" in text and "yes 1,3" in text
    assert "1. Nudge Ivy" in text and "_IHBS_" in text
    assert "✅ (auto) Nudge sent" in text
    assert "⚠️ “Odd task”" in text
    assert "3 lower-priority items" in text


# ---------------------------------------------------------------------------
# build_chase_plan — staging, ranking, cap, autonomy fork
# ---------------------------------------------------------------------------
@pytest.fixture()
def _fake_action(monkeypatch):
    calls = {"staged": [], "ran": []}

    def stage(ctx, client_id, args):
        calls["staged"].append(args)
        if args.get("bad"):
            return "reply", "couldn't resolve a unique target"
        return "confirm", {**args, "_confirm": "do the thing", "_requester": None}

    def run(ctx, client_id, args):
        calls["ran"].append((client_id, args, ctx.profile_id, ctx.role, ctx.source))
        return f"✅ Did {args.get('name')}."

    monkeypatch.setitem(P.PACE_ACTIONS, "test_action",
                        {"label": "test", "stage": stage, "run": run})
    monkeypatch.setattr(P, "PROPOSAL_GENERATORS", [])
    return calls


def _proposal(name, priority=50, kind="nudge", bad=False):
    return {"action": "test_action", "client_id": "c1", "client_name": "Acme",
            "args": {"name": name, "bad": bad}, "reason": f"Do {name}",
            "priority": priority, "kind": kind, "perm": "nudge_other"}


async def test_build_ranks_caps_and_flags(_fake_action, monkeypatch):
    monkeypatch.setattr(settings, "pace_chase_max_items", 2)
    P.PROPOSAL_GENERATORS.append(lambda today: [
        _proposal("low", priority=10), _proposal("high", priority=90),
        _proposal("mid", priority=50, bad=True),
    ])
    plan = await P.build_chase_plan(date(2026, 7, 13))
    # Cap 2 → highest two kept ("high", "mid"); "mid" is unstageable → flag.
    assert [it["reason"] for it in plan["items"]] == ["Do high"]
    assert plan["overflow"] == 1
    assert any("Do mid" in f for f in plan["flags"])
    # Staged args are stripped of confirm metadata and carry min_role.
    assert "_confirm" not in plan["items"][0]["args"]
    assert plan["items"][0]["min_role"] == "staff"  # nudge_other → staff


async def test_build_generator_failure_isolated(_fake_action):
    def boom(today):
        raise RuntimeError("bad generator")
    P.PROPOSAL_GENERATORS.extend([boom, lambda today: [_proposal("ok")]])
    plan = await P.build_chase_plan(date(2026, 7, 13))
    assert len(plan["items"]) == 1


async def test_autonomy_auto_executes_at_build(_fake_action, monkeypatch):
    monkeypatch.setattr(settings, "pace_autonomy", {"nudge": "auto"})
    P.PROPOSAL_GENERATORS.append(lambda today: [_proposal("autoexec")])
    plan = await P.build_chase_plan(date(2026, 7, 13))
    assert plan["items"] == []
    assert plan["auto_results"] == ["✅ Did autoexec."]
    assert len(_fake_action["ran"]) == 1
    assert _fake_action["ran"][0][4] == "system"  # SYSTEM_CONTEXT executed it


# ---------------------------------------------------------------------------
# execute_plan_selection — per-item role authorization
# ---------------------------------------------------------------------------
async def test_selection_respects_roles(_fake_action):
    items = [
        {"index": 1, "action": "test_action", "client_id": "c1", "client_name": "Acme",
         "args": {"name": "a"}, "reason": "Do a", "kind": "nudge", "min_role": "staff"},
        {"index": 2, "action": "test_action", "client_id": "c1", "client_name": "Acme",
         "args": {"name": "b"}, "reason": "Do b", "kind": "month", "min_role": "admin"},
    ]
    # Staff confirms both → item 1 runs, item 2 refused (admin-only).
    reply = await P.execute_plan_selection(items, [1, 2], _staff())
    assert "✅ Did a." in reply and "⛔ 2. Do b" in reply
    assert len(_fake_action["ran"]) == 1
    # Anonymous confirmer runs nothing.
    anon = ActionContext(profile_id=None, role=None, source="slack", slack_user_id="U1")
    reply2 = await P.execute_plan_selection(items, [1], anon)
    assert "Link your Slack account" in reply2
    assert len(_fake_action["ran"]) == 1


async def test_selection_reports_dropped_remainder(_fake_action):
    items = [
        {"index": 1, "action": "test_action", "client_id": "c1", "client_name": "A",
         "args": {"name": "a"}, "reason": "Do a", "kind": "nudge", "min_role": "team_member"},
        {"index": 2, "action": "test_action", "client_id": "c1", "client_name": "A",
         "args": {"name": "b"}, "reason": "Do b", "kind": "nudge", "min_role": "team_member"},
    ]
    reply = await P.execute_plan_selection(items, [1], _staff())
    assert "1 unselected item dropped" in reply


# ---------------------------------------------------------------------------
# Daily runner — gates + dedupe + supersede
# ---------------------------------------------------------------------------
async def test_runner_gated(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", False)
    out = await P.run_daily_chase_plan(date(2026, 7, 13))
    assert out == {"posted": False, "reason": "disabled"}


async def test_runner_all_clear_posts_nothing(monkeypatch, _fake_action):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    emitted = {}
    monkeypatch.setattr(P.notifications, "emit", lambda **kw: emitted.update(kw) or "nid")
    out = await P.run_daily_chase_plan(date(2026, 7, 13))
    assert out == {"posted": False, "reason": "all_clear"} and not emitted


async def test_runner_dedupes_on_notification(monkeypatch, _fake_action):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    P.PROPOSAL_GENERATORS.append(lambda today: [_proposal("x")])
    # emit returns None ⇒ someone already posted today's plan ⇒ no Slack post.
    monkeypatch.setattr(P.notifications, "emit", lambda **kw: None)
    out = await P.run_daily_chase_plan(date(2026, 7, 13))
    assert out == {"posted": False, "reason": "deduped"}


async def test_runner_posts_and_registers_batch(monkeypatch, _fake_action):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(settings, "pace_slack_channel", "Cpace")
    P.PROPOSAL_GENERATORS.append(lambda today: [_proposal("x")])
    monkeypatch.setattr(P.notifications, "emit", lambda **kw: "nid")

    async def fake_post(channel, text, thread_ts=None):
        assert channel == "Cpace" and "chase plan" in text.lower()
        return "111.222"

    # The runner imports post_message from the PACKAGE at call time — patch the
    # package re-export (patching llm.post_message would not rebind it).
    monkeypatch.setattr("services.slack_assistant.post_message", fake_post)
    from services import pace_agent
    pace_agent._pace_pending.clear()
    # Seed a stale "yesterday" plan to prove supersession.
    P._last_plan_key = ("Cpace", "000.111")
    pace_agent._pace_pending[("Cpace", "000.111")] = {"batch": True, "items": []}

    out = await P.run_daily_chase_plan(date(2026, 7, 13))
    assert out == {"posted": True, "confirmable": True, "items": 1}
    assert ("Cpace", "000.111") not in pace_agent._pace_pending  # superseded
    entry = pace_agent._pace_pending[("Cpace", "111.222")]
    assert entry["batch"] is True and len(entry["items"]) == 1
    pace_agent._pace_pending.clear()
    P._last_plan_key = None
