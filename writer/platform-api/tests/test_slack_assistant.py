"""Unit tests for the Slack assistant pure helpers (no network)."""

from __future__ import annotations

import hashlib
import hmac

from services import slack_assistant


SECRET = "shhh-signing-secret"


def _sign(timestamp: str, body: str, secret: str = SECRET) -> str:
    base = f"v0:{timestamp}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# verify_slack_signature
# ---------------------------------------------------------------------------
def test_signature_valid():
    ts, body = "1000000", '{"type":"event_callback"}'
    sig = _sign(ts, body)
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000005) is True


def test_signature_wrong_secret_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body, secret="other")
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000005) is False


def test_signature_tampered_body_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body)
    assert slack_assistant.verify_slack_signature(SECRET, ts, "{tampered}", sig, now_ts=1000005) is False


def test_signature_stale_timestamp_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body)
    # 10 minutes later → outside the 5-min replay window.
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000000 + 600) is False


def test_signature_missing_pieces_fail_closed():
    assert slack_assistant.verify_slack_signature("", "1", "b", "v0=x", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "", "b", "v0=x", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "1", "b", "", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "notanint", "b", "v0=x", 1) is False


# ---------------------------------------------------------------------------
# strip_mention
# ---------------------------------------------------------------------------
def test_strip_mention():
    assert slack_assistant.strip_mention("<@U12345> how is Acme?") == "how is Acme?"
    assert slack_assistant.strip_mention("hey <@U1> and <@U2> ping") == "hey  and  ping".strip()
    assert slack_assistant.strip_mention("   ") == ""
    assert slack_assistant.strip_mention(None) == ""


# ---------------------------------------------------------------------------
# resolve_client
# ---------------------------------------------------------------------------
_CLIENTS = [
    {"id": "1", "name": "Acme"},
    {"id": "2", "name": "Acme Plumbing"},
    {"id": "3", "name": "Bright Dental"},
]


def test_resolve_prefers_longest_full_name():
    c = slack_assistant.resolve_client("how is acme plumbing doing this month?", _CLIENTS)
    assert c["id"] == "2"


def test_resolve_exact_short_name():
    c = slack_assistant.resolve_client("any drops for Acme?", _CLIENTS)
    assert c["id"] == "1"


def test_resolve_token_overlap_fallback():
    # "dental" isn't the full name but is a distinctive token of "Bright Dental".
    c = slack_assistant.resolve_client("hows the dental account", _CLIENTS)
    assert c["id"] == "3"


def test_resolve_none_when_no_match():
    assert slack_assistant.resolve_client("how are rankings overall?", _CLIENTS) is None
    assert slack_assistant.resolve_client("", _CLIENTS) is None


def test_resolve_ignores_generic_tokens():
    # "services" is a stop word — shouldn't match a client named "... Services".
    clients = [{"id": "9", "name": "Premier Services"}]
    assert slack_assistant.resolve_client("what about our other services", clients) is None


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# build_context registry behavior (providers isolated; empties omitted)
# ---------------------------------------------------------------------------
def test_build_context_assembles_isolates_and_omits(monkeypatch):
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: object())

    def good(sb, cid, today):
        return {"ok": True}

    def empty(sb, cid, today):
        return None

    def boom(sb, cid, today):
        raise RuntimeError("module down")

    monkeypatch.setattr(
        slack_assistant,
        "_CONTEXT_PROVIDERS",
        [("alpha", good), ("beta", empty), ("gamma", boom)],
    )
    ctx = slack_assistant.build_context("client-1")
    assert ctx == {"alpha": {"ok": True}}  # empty omitted, failing one isolated


def test_format_history_labels_roles_and_skips_empty():
    out = slack_assistant.format_history([
        {"role": "user", "content": "how is Acme?"},
        {"role": "assistant", "content": "Acme is #4, steady."},
        {"role": "user", "content": "  "},
        {"role": "user", "content": "what about Maps?"},
    ])
    assert out == (
        "Teammate: how is Acme?\n"
        "SerMastr: Acme is #4, steady.\n"
        "Teammate: what about Maps?"
    )


def test_format_history_empty():
    assert slack_assistant.format_history([]) == ""


# ---------------------------------------------------------------------------
# weak_cities (shape-tolerant — the real stored value is an object, not a list)
# ---------------------------------------------------------------------------
def test_weak_cities_from_object_shape():
    rwl = {"geocoded": True, "capped": False, "weak_areas": [
        {"city": "Port Melbourne", "pins": 5},
        {"city": "Toorak", "pins": 3},
        {"pins": 1},  # no city → skipped
    ]}
    assert slack_assistant.weak_cities(rwl) == ["Port Melbourne", "Toorak"]


def test_weak_cities_from_list_shape():
    assert slack_assistant.weak_cities([{"city": "A"}, {"city": "B"}]) == ["A", "B"]


def test_weak_cities_tolerates_none_and_junk():
    assert slack_assistant.weak_cities(None) == []
    assert slack_assistant.weak_cities("oops") == []
    assert slack_assistant.weak_cities({"weak_areas": None}) == []


def test_weak_cities_caps_at_five():
    rwl = {"weak_areas": [{"city": f"C{i}"} for i in range(9)]}
    assert slack_assistant.weak_cities(rwl) == ["C0", "C1", "C2", "C3", "C4"]


# ---------------------------------------------------------------------------
# is_affirmative (confirmation of a pending paid action)
# ---------------------------------------------------------------------------
def test_is_affirmative_accepts_yeses():
    for t in ["yes", "Yes", "YES!", "yep", "yeah", "confirm", "do it", "go ahead",
              "proceed", "ok", "sure", "yes please", "yes, go"]:
        assert slack_assistant.is_affirmative(t) is True, t


def test_is_affirmative_rejects_others():
    for t in ["no", "not yet", "what?", "how is acme", "yesterday", "", "maybe"]:
        assert slack_assistant.is_affirmative(t) is False, t


# ---------------------------------------------------------------------------
# action registry/tools consistency
# ---------------------------------------------------------------------------
def test_action_tools_match_registry():
    tool_names = {t["name"] for t in slack_assistant._ACTION_TOOLS}
    assert tool_names == set(slack_assistant._ACTIONS)
    for meta in slack_assistant._ACTIONS.values():
        assert callable(meta["run"])
        assert isinstance(meta["paid"], bool)
    # exactly one free action (rebuild plan), the scans are paid.
    assert slack_assistant._ACTIONS["rebuild_action_plan"]["paid"] is False
    assert all(slack_assistant._ACTIONS[k]["paid"] for k in
               ("run_maps_scan", "run_gsc_research", "run_ai_visibility_scan"))
    # the Asana push isn't API spend but still confirm-gated (creates real
    # tasks) — with its own confirm wording.
    push = slack_assistant._ACTIONS["push_task_plan"]
    assert push["paid"] is True
    assert "Asana" in push["note"]
    # the task-management actions are parameterized + staged, and their tool
    # schemas carry the params so Claude can fill them.
    for name in ("add_asana_task", "remove_asana_task", "complete_asana_task"):
        meta = slack_assistant._ACTIONS[name]
        assert meta["paid"] is True and callable(meta["stage"])
        tool = next(t for t in slack_assistant._ACTION_TOOLS if t["name"] == name)
        assert "task_name" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["task_name"]


# ---------------------------------------------------------------------------
# conversational task management
# ---------------------------------------------------------------------------
def test_match_open_tasks_exact_beats_substring_and_skips_completed():
    tasks = [
        {"gid": "1", "name": "Citations", "completed": False},
        {"gid": "2", "name": "Citations — batch 2", "completed": False},
        {"gid": "3", "name": "Citations — batch 3", "completed": True},
    ]
    # exact name → only that task, even though others contain the query
    assert [t["gid"] for t in slack_assistant.match_open_tasks(tasks, "citations")] == ["1"]
    # substring → open matches only (the completed batch 3 never surfaces)
    assert [t["gid"] for t in slack_assistant.match_open_tasks(tasks, "batch")] == ["2"]
    assert slack_assistant.match_open_tasks(tasks, "") == []
    assert slack_assistant.match_open_tasks(tasks, "nothing") == []


def test_stage_pick_task_resolves_disambiguates_and_guards(monkeypatch):
    import asyncio

    from services import asana_service

    monkeypatch.setattr(slack_assistant, "_asana_ready", lambda cid: ("777", None))
    tasks = [
        {"gid": "t1", "name": "Fix GBP categories", "completed": False,
         "assignee": {"name": "Ivy Gervacio"}},
        {"gid": "t2", "name": "Fix citations", "completed": False, "assignee": None},
    ]

    async def fake_list(project_gid):
        return tasks

    monkeypatch.setattr(asana_service, "list_project_tasks", fake_list)

    # one match → staged with the exact gid + a confirm naming task & assignee
    outcome, staged = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "gbp"}, "permanently delete")
    )
    assert outcome == "confirm"
    assert staged["task_gid"] == "t1"
    assert "Fix GBP categories" in staged["_confirm"] and "Ivy Gervacio" in staged["_confirm"]

    # several matches → immediate disambiguation reply, nothing staged
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "fix"}, "permanently delete")
    )
    assert outcome == "reply" and "matches 2 open tasks" in reply

    # no match → the open tasks are listed back
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "zzz"}, "permanently delete")
    )
    assert outcome == "reply" and "Fix GBP categories" in reply

    # unready Asana → the guard's guidance passes straight through
    monkeypatch.setattr(slack_assistant, "_asana_ready", lambda cid: (None, "not set up"))
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "gbp"}, "permanently delete")
    )
    assert outcome == "reply" and reply == "not set up"


def test_stage_add_task_matches_assignee_and_flags_unknown(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    monkeypatch.setattr(slack_assistant, "_asana_ready", lambda cid: ("777", None))
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"gid": "g1", "name": "Ivy Gervacio"},
    ]
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: supabase)

    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task("c1", {"task_name": "Audit citations", "assignee": "Ivy"})
    )
    assert outcome == "confirm"
    assert staged["assignee_gid"] == "g1"
    assert "Ivy Gervacio" in staged["_confirm"]

    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task("c1", {"task_name": "Audit citations", "assignee": "Bob"})
    )
    assert outcome == "confirm"
    assert staged["assignee_gid"] is None
    assert "couldn't match" in staged["_confirm"]

    outcome, reply = asyncio.run(slack_assistant._stage_add_task("c1", {}))
    assert outcome == "reply"


def test_run_action_awaits_async_runners(monkeypatch):
    import asyncio

    async def async_runner(client_id, args=None):
        return f"async:{client_id}"

    def sync_runner(client_id, args=None):
        return f"sync:{client_id}"

    monkeypatch.setitem(slack_assistant._ACTIONS, "add_asana_task",
                        {**slack_assistant._ACTIONS["add_asana_task"], "run": async_runner})
    monkeypatch.setitem(slack_assistant._ACTIONS, "rebuild_action_plan",
                        {**slack_assistant._ACTIONS["rebuild_action_plan"], "run": sync_runner})
    assert asyncio.run(slack_assistant._run_action("add_asana_task", "c1", {})) == "async:c1"
    assert asyncio.run(slack_assistant._run_action("rebuild_action_plan", "c1", None)) == "sync:c1"


def test_push_task_plan_action_guards_and_enqueues(monkeypatch):
    from unittest.mock import MagicMock

    from services import asana_monthly, asana_push, asana_service

    monkeypatch.setattr(asana_service, "is_configured", lambda: True)
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: "777")

    # no plan row → guidance, nothing enqueued
    supabase = MagicMock()
    chain = supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute
    chain.return_value.data = []
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: supabase)
    enqueued = []
    monkeypatch.setattr(asana_push, "enqueue_asana_push", lambda cid, pid: enqueued.append((cid, pid)))
    out = slack_assistant._act_push_task_plan("c1")
    assert "No monthly task plan" in out and not enqueued

    # empty plan → guidance, nothing enqueued
    chain.return_value.data = [{"id": "p1", "month": "2026-07-01", "plan": {"tasks": []}}]
    out = slack_assistant._act_push_task_plan("c1")
    assert "no task lines" in out and not enqueued

    # real plan → enqueued
    chain.return_value.data = [{"id": "p1", "month": "2026-07-01", "plan": {"tasks": [{"task_type": "das_v2"}]}}]
    out = slack_assistant._act_push_task_plan("c1")
    assert enqueued == [("c1", "p1")]
    assert "Pushing the latest task plan" in out

    # unmapped project → guidance
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: None)
    out = slack_assistant._act_push_task_plan("c1")
    assert "no Asana project mapped" in out


def test_format_context_is_json_with_client():
    import json

    out = slack_assistant.format_context(
        {"name": "Acme", "website_url": "https://acme.com"},
        {"keyword_count": 3, "open_drop_alerts": []},
    )
    parsed = json.loads(out)
    assert parsed["client"]["name"] == "Acme"
    assert parsed["client"]["website"] == "https://acme.com"
    assert parsed["keyword_count"] == 3


# ---------------------------------------------------------------------------
# SOP grounding — the strategy-question gate + domain selection (pure).
# ---------------------------------------------------------------------------
def test_wants_sop_grounding_matches_strategy_shapes():
    for q in (
        "How is our strategy working?",
        "Should we change the approach for Acme?",
        "What's the forecast for next quarter?",
        "What should we improve?",
        "Why did rankings drop last week?",
        "How do we grow GBP reviews?",
        "Can we shift budget into link building?",
        "how should we prioritize the action plan",
    ):
        assert slack_assistant.wants_sop_grounding(q), q


def test_wants_sop_grounding_skips_pure_data_reads():
    for q in (
        "What's our rank for roof repair?",
        "Show me the tracked keywords",
        "Who are the top competitors?",
        "add an asana task for Ivy",
    ):
        assert not slack_assistant.wants_sop_grounding(q), q
    assert not slack_assistant.wants_sop_grounding("")
    assert not slack_assistant.wants_sop_grounding(None)


def test_sop_domains_from_question_keywords():
    assert "maps" in slack_assistant.sop_domains("how do we win the local pack?", {})
    assert "ai_visibility" in slack_assistant.sop_domains("why is ChatGPT not mentioning us", {})
    assert "offpage" in slack_assistant.sop_domains("do we need more backlinks?", {})
    assert "budget" in slack_assistant.sop_domains("where should the retainer go", {})
    assert "content" in slack_assistant.sop_domains("plan more blog content", {})
    assert "organic_drop" in slack_assistant.sop_domains("rankings fell — is this cannibalization?", {})


def test_sop_domains_from_context_signals():
    ctx = {
        "organic_rank": {"open_drop_alerts": [{"keyword": "roof repair"}]},
        "maps_geogrid": {"scans": []},
        "ai_visibility": {"visibility": 40},
    }
    domains = slack_assistant.sop_domains("how is the campaign going", ctx)
    assert {"organic_drop", "maps", "ai_visibility"} <= domains
    # No alerts / modules → no context-driven domains.
    assert slack_assistant.sop_domains("how is the campaign going", {"organic_rank": {}}) == set()


def test_read_sop_tool_lists_docs():
    tool = slack_assistant._read_sop_tool()
    assert tool["name"] == "read_sop"
    assert "doc" in tool["input_schema"]["properties"]
    # The live SOP corpus is vendored into the service — the catalog should name it.
    assert "How_To_Rank_In_Google_Maps_SOP.md" in tool["description"]
