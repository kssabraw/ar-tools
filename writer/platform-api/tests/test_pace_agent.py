"""Tests for the PACE conversational persona/router (Phase 3).

Pure routers + tool schemas + the deterministic portfolio/personal-brief text,
plus the actor-bound web confirm path (the risky bit) with the small DB reads
and the action run monkeypatched. The LLM loop itself is not exercised here —
`interpret_pace` is a thin `_one_llm_call` wrapper covered by the slack_assistant
suite; these tests pin the routing + gating + actor-binding around it.
"""

from __future__ import annotations

from datetime import date

from services import pace_agent
from services.pace_agent import PACE_ACTIONS
from services.pace_auth import ActionContext


def test_referenced_config_keys_exist():
    """Regression guard: every settings.pace_* the persona/digest touch at
    runtime must be defined on the settings object (a missing key AttributeErrors
    only once pace_enabled is flipped — invisible to the default-off suite)."""
    from config import settings

    for key in ("pace_enabled", "pace_model", "pace_max_tokens", "pace_digest_weekday_only",
                # v1.4 initiative keys — every one the engine/generators read.
                "pace_initiative_enabled", "pace_autonomy", "pace_chase_max_items",
                "pace_chase_renudge_days", "pace_chase_escalate_business_days",
                "pace_slip_horizon_days", "pace_daily_brief_push"):
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
async def test_force_handles_non_pace_message(monkeypatch):
    # In the dedicated PACE channel (force=True), even a non-delivery message is
    # handled by PACE instead of falling through (is_pace_message gate skipped).
    posted = {}

    async def _post(channel, text, thread_ts):
        posted.update(channel=channel, text=text)

    monkeypatch.setattr("services.slack_assistant.post_message", _post)
    monkeypatch.setattr("services.slack_assistant.strip_mention", lambda t: t)
    monkeypatch.setattr("services.slack_assistant.is_affirmative", lambda t: False)
    monkeypatch.setattr("services.slack_assistant.resolve_client", lambda q, cs: None)
    monkeypatch.setattr(pace_agent, "_portfolio_pace_text", lambda: "portfolio delivery read")
    monkeypatch.setattr(pace_agent, "get_supabase",
                        lambda: type("SB", (), {"table": lambda *a, **k: type("Q", (), {
                            "select": lambda *a, **k: type("Q2", (), {"execute": lambda *a, **k: type("R", (), {"data": []})()})()})()})())
    event = {"channel": "Cpace", "ts": "1", "text": "how is the campaign going?"}
    handled = await pace_agent.maybe_handle_slack(event, _staff(), force=True)
    assert handled is True  # force → PACE answered (didn't fall through)


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


# ---------------------------------------------------------------------------
# Fake Supabase — routes reads by table name to preset rows. The server-side
# filters are ignored (Python-side match_open_tasks / bucket_by_due still run on
# the returned rows), so the tests exercise the real routing logic.
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, _name):
        # select/eq/is_/not_/in_/limit/order… all chain back to self.
        def _chain(*a, **k):
            return self
        return _chain

    @property
    def not_(self):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeSB:
    def __init__(self, by_table):
        self._by_table = by_table

    def table(self, name):
        return _FakeQuery(self._by_table.get(name, []))


def _fake_supabase(monkeypatch, by_table):
    monkeypatch.setattr(pace_agent, "get_supabase", lambda: _FakeSB(by_table))


# ---------------------------------------------------------------------------
# resolve_member — the per-staff-member scope gate (pure)
# ---------------------------------------------------------------------------
def test_resolve_member_full_and_first_name():
    members = [{"gid": "g1", "name": "Ivy Chen"}, {"gid": "g2", "name": "Marcus Bell"}]
    assert pace_agent.resolve_member("what does Ivy have overdue?", members)["gid"] == "g1"
    assert pace_agent.resolve_member("is Marcus Bell behind?", members)["gid"] == "g2"
    # No roster name present → None (→ falls to portfolio/client scope).
    assert pace_agent.resolve_member("what's overdue across everything?", members) is None
    # Substrings of other words don't false-match (whole-word only).
    assert pace_agent.resolve_member("ivory tower tasks", members) is None


def test_resolve_member_longest_match_wins():
    members = [{"gid": "g1", "name": "Jo"}, {"gid": "g2", "name": "Joanna Reed"}]
    # "Jo" is < 3 chars so it's skipped; "Joanna" wins on the full string.
    assert pace_agent.resolve_member("what does Joanna have?", members)["gid"] == "g2"


# ---------------------------------------------------------------------------
# build_member_context — a member's open tasks across all clients, bucketed
# ---------------------------------------------------------------------------
def test_build_member_context_buckets_and_names(monkeypatch):
    tasks = [
        {"id": "t1", "client_id": "c1", "name": "GBP audit", "due_date": "2020-01-01", "status_key": "in_progress"},
        {"id": "t2", "client_id": "c2", "name": "Blog draft", "due_date": "2999-01-01", "status_key": "not_started"},
        {"id": "t3", "client_id": "c1", "name": "No due task", "due_date": None, "status_key": "not_started"},
    ]
    _fake_supabase(monkeypatch, {
        "tasks": tasks,
        "clients": [{"id": "c1", "name": "Acme"}, {"id": "c2", "name": "Globex"}],
    })
    ctx = pace_agent.build_member_context({"gid": "g1", "name": "Ivy"}, today=date(2024, 6, 1))
    assert ctx["member"] == "Ivy" and ctx["open_count"] == 3
    assert [r["name"] for r in ctx["overdue"]] == ["GBP audit"]
    assert ctx["overdue"][0]["client"] == "Acme"           # client name attached
    assert [r["name"] for r in ctx["later"]] == ["Blog draft"]
    assert [r["name"] for r in ctx["no_due_date"]] == ["No due task"]


# ---------------------------------------------------------------------------
# build_portfolio_context — full lists (not counts) with client names + caps
# ---------------------------------------------------------------------------
def test_build_portfolio_context_attaches_names_and_caps(monkeypatch):
    big = [{"id": f"t{i}", "name": f"task {i}"} for i in range(pace_agent._PORTFOLIO_ROW_CAP + 5)]
    monkeypatch.setattr(pace_agent.pm_signals, "build_board_digest",
                        lambda cid, today=None: {"clients": [{"client_id": "c1", "overdue": big, "stale": []}]})
    _fake_supabase(monkeypatch, {"clients": [{"id": "c1", "name": "Acme"}]})
    ctx = pace_agent.build_portfolio_context()
    c = ctx["clients"][0]
    assert c["client_name"] == "Acme"
    # Capped to the row cap + a truncation marker (so the LLM says "and N more").
    assert len(c["overdue"]) == pace_agent._PORTFOLIO_ROW_CAP + 1
    assert c["overdue"][-1] == {"_truncated": 5}


# ---------------------------------------------------------------------------
# _resolve_task_client — cross-client action target resolution
# ---------------------------------------------------------------------------
def test_resolve_task_client_unique(monkeypatch):
    _fake_supabase(monkeypatch, {
        "tasks": [{"id": "t1", "name": "GBP audit", "client_id": "c1"}],
        "clients": [{"id": "c1", "name": "Acme"}],
    })
    client, reply = pace_agent._resolve_task_client("GBP audit")
    assert reply is None and client["id"] == "c1" and client["name"] == "Acme"


def test_resolve_task_client_spans_clients(monkeypatch):
    _fake_supabase(monkeypatch, {
        "tasks": [{"id": "t1", "name": "GBP audit", "client_id": "c1"},
                  {"id": "t2", "name": "GBP audit", "client_id": "c2"}],
        "clients": [{"id": "c1", "name": "Acme"}, {"id": "c2", "name": "Globex"}],
    })
    client, reply = pace_agent._resolve_task_client("GBP audit")
    assert client is None and "more than one client" in reply


def test_resolve_task_client_no_match(monkeypatch):
    _fake_supabase(monkeypatch, {"tasks": [{"id": "t1", "name": "GBP audit", "client_id": "c1"}]})
    client, reply = pace_agent._resolve_task_client("nonexistent")
    assert client is None and "No open task" in reply


# ---------------------------------------------------------------------------
# _answer — scope routing + enumeration feed (the fix for "just a count")
# ---------------------------------------------------------------------------
async def test_answer_member_scope_feeds_member_context(monkeypatch):
    """A named member routes to member scope and the member's task list — not a
    client digest, not a count — is what interpret_pace is handed."""
    captured = {}

    async def _fake_interpret(question, client, ctx, history, style, on_event, scope="client"):
        captured.update(scope=scope, ctx=ctx, client=client)
        return ("text", "Ivy has 1 overdue: GBP audit (Acme).")

    monkeypatch.setattr(pace_agent, "interpret_pace", _fake_interpret)
    monkeypatch.setattr(pace_agent, "_all_clients", lambda: [{"id": "c9", "name": "Zeta"}])
    monkeypatch.setattr(pace_agent, "_active_members", lambda: [{"gid": "g1", "name": "Ivy"}])
    monkeypatch.setattr(pace_agent, "build_member_context",
                        lambda m, today=None: {"member": "Ivy", "overdue": [{"name": "GBP audit"}]})
    out = await pace_agent._answer("what does Ivy have overdue?", None, None, _staff(), "web", None,
                                   pace_agent._run_direct)
    assert captured["scope"] == "member"
    assert captured["client"] is None
    assert captured["ctx"]["overdue"] == [{"name": "GBP audit"}]   # real rows, not a total
    assert out["reply"].startswith("Ivy has 1 overdue")


async def test_answer_portfolio_action_resolves_task_client(monkeypatch):
    """In portfolio scope an action (reassign) names a task; PACE resolves which
    client's board it lives on before staging."""
    async def _fake_interpret(question, client, ctx, history, style, on_event, scope="client"):
        return ("action", {"name": "reassign_task", "args": {"task_name": "GBP audit", "assignee": "Marcus"}})

    async def _fake_stage(name, actor, client_id, args):
        assert client_id == "c1"        # resolved from the task, not the (absent) client scope
        return "confirm", {"task_id": "t1", "_confirm": "reassign it", "_requester": actor.profile_id}

    monkeypatch.setattr(pace_agent, "interpret_pace", _fake_interpret)
    monkeypatch.setattr(pace_agent, "_stage", _fake_stage)
    monkeypatch.setattr(pace_agent, "_all_clients", lambda: [])
    monkeypatch.setattr(pace_agent, "_active_members", lambda: [])
    monkeypatch.setattr(pace_agent, "build_portfolio_context", lambda today=None: {"clients": []})
    monkeypatch.setattr(pace_agent, "_resolve_task_client",
                        lambda name: ({"id": "c1", "name": "Acme"}, None))
    out = await pace_agent._answer("reassign the GBP audit to Marcus", None, None, _staff(), "web", None,
                                   pace_agent._run_direct)
    assert out["pending"]["name"] == "reassign_task"
    assert out["pending"]["client_id"] == "c1" and out["pending"]["confirm"] == "reassign it"
    assert out["pending"]["requester"] == "p_staff"


async def test_answer_taskless_action_needs_client(monkeypatch):
    async def _fake_interpret(question, client, ctx, history, style, on_event, scope="client"):
        return ("action", {"name": "generate_client_month", "args": {}})

    monkeypatch.setattr(pace_agent, "interpret_pace", _fake_interpret)
    monkeypatch.setattr(pace_agent, "_all_clients", lambda: [])
    monkeypatch.setattr(pace_agent, "_active_members", lambda: [])
    monkeypatch.setattr(pace_agent, "build_portfolio_context", lambda today=None: {"clients": []})
    out = await pace_agent._answer("generate the month", None, None, _staff(), "web", None, pace_agent._run_direct)
    assert "Name the client" in out["reply"]


# ---------------------------------------------------------------------------
# Structural autonomy (v1.5) — batch staging + drill-down
# ---------------------------------------------------------------------------
async def test_stage_batch_stages_and_flags(monkeypatch):
    async def _fake_stage(action, actor, client_id, args):
        if args["task_name"] == "bad":
            return "reply", "unassigned — nobody to nudge"
        return "confirm", {"task_id": "x", "_confirm": f"nudge about “{args['task_name']}”",
                           "_requester": actor.profile_id}

    monkeypatch.setattr(pace_agent, "_stage", _fake_stage)
    targets = [{"client_id": "c1", "client_name": "Acme", "task_name": "GBP audit"},
               {"client_id": "c1", "client_name": "Acme", "task_name": "bad"}]
    items, flags = await pace_agent._stage_batch("nudge_assignee", targets, {}, _staff())
    assert len(items) == 1 and items[0]["index"] == 1 and items[0]["client_id"] == "c1"
    assert items[0]["min_role"] is None                     # pre-authorized at stage
    assert items[0]["reason"].startswith("nudge about")
    assert flags == ["“bad” — unassigned — nobody to nudge"]


async def test_build_batch_success(monkeypatch):
    monkeypatch.setattr(pace_agent.pace_batch, "select_targets",
                        lambda *a, **k: ([{"client_id": "c1", "client_name": "Acme", "task_name": "GBP"}], 2))

    async def _fake_stage_batch(action, targets, extra, actor):
        assert extra == {"assignee": "Marcus"}             # reassign threads the assignee
        return ([{"index": 1, "action": action, "client_id": "c1", "client_name": "Acme",
                  "args": {}, "reason": "reassign", "min_role": None}], [])

    monkeypatch.setattr(pace_agent, "_stage_batch", _fake_stage_batch)
    out = await pace_agent._build_batch(
        {"action": "reassign_task", "selector": "overdue", "assignee": "Marcus"},
        "client", {"id": "c1", "name": "Acme"}, {}, _staff(), {"client_id": "c1", "client_name": "Acme"})
    assert out["batch"]["requester"] == "p_staff" and out["batch"]["overflow"] == 2
    assert out["batch"]["items"][0]["reason"] == "reassign"


async def test_build_batch_rejects_unknown_action():
    out = await pace_agent._build_batch({"action": "delete_all", "selector": "overdue"},
                                        "client", {"id": "c1"}, {}, _staff(), {})
    assert "batch nudge" in out["reply"]


async def test_build_batch_no_targets(monkeypatch):
    monkeypatch.setattr(pace_agent.pace_batch, "select_targets", lambda *a, **k: ([], 0))
    out = await pace_agent._build_batch({"action": "nudge_assignee", "selector": "overdue"},
                                        "client", {"id": "c1"}, {}, _staff(), {})
    assert "No overdue tasks" in out["reply"]


async def test_answer_batch_kind_routes_to_build_batch(monkeypatch):
    async def _fake_interpret(*a, **k):
        return ("batch", {"action": "nudge_assignee", "selector": "overdue"})

    async def _fake_build(payload, scope, subject, ctx, actor, base):
        return {**base, "batch": {"items": [{"index": 1}], "flags": [], "overflow": 0,
                                  "requester": actor.profile_id}}

    monkeypatch.setattr(pace_agent, "interpret_pace", _fake_interpret)
    monkeypatch.setattr(pace_agent, "_resolve_scope",
                        lambda q, s: ("client", {"id": "c1", "name": "Acme"}, {"overdue": [{"name": "GBP"}]}))
    monkeypatch.setattr(pace_agent, "_build_batch", _fake_build)
    out = await pace_agent._answer("nudge all overdue", None, None, _staff(), "web", None, pace_agent._run_direct)
    assert out["batch"]["requester"] == "p_staff"


async def test_web_batch_confirm_runs_selection(monkeypatch):
    pace_agent._pace_web_pending.clear()
    items = [{"index": 1, "action": "nudge_assignee", "client_id": "c1", "client_name": "Acme",
              "args": {}, "reason": "nudge", "min_role": None}]
    token = pace_agent._store_web_batch(items, requester="p_staff")
    called = {}

    async def _fake_exec(items_, selection, ctx):
        called.update(selection=selection, actor=ctx.profile_id)
        return "✅ nudged"

    monkeypatch.setattr("services.pace_proposals.execute_plan_selection", _fake_exec)
    out = await pace_agent.maybe_handle_web("yes", [], None, token, _staff())
    assert out["reply"] == "✅ nudged" and called["selection"] == [1] and called["actor"] == "p_staff"
    pace_agent._pace_web_pending.clear()


async def test_web_batch_confirm_actor_binding_refuses_other(monkeypatch):
    pace_agent._pace_web_pending.clear()
    items = [{"index": 1, "action": "nudge_assignee", "client_id": "c1", "client_name": "Acme",
              "args": {}, "reason": "n", "min_role": None}]
    token = pace_agent._store_web_batch(items, requester="p_staff")
    ran = {"n": 0}

    async def _fake_exec(*a):
        ran["n"] += 1
        return "x"

    monkeypatch.setattr("services.pace_proposals.execute_plan_selection", _fake_exec)
    out = await pace_agent.maybe_handle_web(
        "yes", [], None, token, ActionContext(profile_id="p_other", role="staff", source="web"))
    assert "Only the person who requested" in out["reply"] and ran["n"] == 0
    pace_agent._pace_web_pending.clear()


def test_drill_read_formats_detail(monkeypatch):
    _fake_supabase(monkeypatch, {"tasks": [{"id": "t1", "name": "GBP audit", "client_id": "c1"}]})
    monkeypatch.setattr("services.task_service.get_task_detail",
                        lambda tid: {"name": "GBP audit", "status_key": "in_progress",
                                     "activity": [{"created_at": "2026-07-10", "kind": "created"}], "subtasks": []})
    monkeypatch.setattr("services.task_collab.list_comments", lambda tid: [])
    out = pace_agent._drill_read("GBP", "c1")
    assert "Task: GBP audit" in out and "Status: in_progress" in out


def test_drill_read_no_match(monkeypatch):
    _fake_supabase(monkeypatch, {"tasks": [{"id": "t1", "name": "GBP audit", "client_id": "c1"}]})
    assert "No open task matches" in pace_agent._drill_read("nonexistent", "c1")
