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
# admin actions — pure helpers
# ---------------------------------------------------------------------------
def test_match_named_exact_beats_substring():
    rows = [
        {"id": "1", "keyword": "roof repair"},
        {"id": "2", "keyword": "roof repair near me"},
    ]
    assert [r["id"] for r in slack_assistant.match_named(rows, "roof repair", key="keyword")] == ["1"]
    assert [r["id"] for r in slack_assistant.match_named(rows, "near", key="keyword")] == ["2"]
    assert slack_assistant.match_named(rows, "", key="keyword") == []
    assert slack_assistant.match_named(rows, "zzz", key="keyword") == []


def test_merge_cities_dedupes_case_insensitively():
    merged, added, already = slack_assistant.merge_cities(
        ["Austin", "Round Rock"], ["round rock", "Pflugerville", "  ", "pflugerville"]
    )
    assert merged == ["Austin", "Round Rock", "Pflugerville"]
    assert added == ["Pflugerville"]
    assert already == ["round rock"]


def test_merge_cities_from_empty():
    merged, added, already = slack_assistant.merge_cities(None, ["Austin"])
    assert merged == ["Austin"] and added == ["Austin"] and already == []


def test_drop_cities_matches_stored_casing_and_reports_missing():
    remaining, removed, missing = slack_assistant.drop_cities(
        ["Austin", "Round Rock", "Pflugerville"], ["round rock", "Nowhere"]
    )
    assert remaining == ["Austin", "Pflugerville"]
    assert removed == ["Round Rock"]  # stored casing
    assert missing == ["Nowhere"]


def test_coerce_profile_value_typing():
    assert slack_assistant.coerce_profile_value("retainer_monthly", "$4,500") == (4500.0, None)
    assert slack_assistant.coerce_profile_value("retainer_monthly", "lots")[1] is not None
    assert slack_assistant.coerce_profile_value("client_type", "Enterprise") == ("enterprise", None)
    assert slack_assistant.coerce_profile_value("client_type", "franchise")[1] is not None
    assert slack_assistant.coerce_profile_value("is_sab", "yes") == (True, None)
    assert slack_assistant.coerce_profile_value("is_sab", "no") == (False, None)
    assert slack_assistant.coerce_profile_value("is_sab", "maybe")[1] is not None
    assert slack_assistant.coerce_profile_value("website_url", "acme.com") == ("https://acme.com", None)
    assert slack_assistant.coerce_profile_value("website_url", "https://acme.com") == ("https://acme.com", None)
    assert slack_assistant.coerce_profile_value("gsc_property", " sc-domain:acme.com ") == ("sc-domain:acme.com", None)
    # non-editable / empty → error
    assert slack_assistant.coerce_profile_value("name", "Acme")[1] is not None
    assert slack_assistant.coerce_profile_value("wordpress_app_password", "x")[1] is not None
    assert slack_assistant.coerce_profile_value("website_url", "")[1] is not None


def test_clean_list_trims_and_dedupes():
    assert slack_assistant._clean_list(["  Austin ", "austin", "", None, "Waco"]) == ["Austin", "Waco"]
    assert slack_assistant._clean_list(None) == []


# ---------------------------------------------------------------------------
# admin actions — staging (mocked DB)
# ---------------------------------------------------------------------------
def test_stage_update_profile_confirms_change_and_skips_noop(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        slack_assistant, "_client_row", lambda cid, cols: {"retainer_monthly": 3000.0}
    )
    outcome, staged = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "retainer_monthly", "value": "$4,500"})
    )
    assert outcome == "confirm"
    assert staged["coerced_value"] == 4500.0
    assert "$4,500" in staged["_confirm"] and "$3,000" in staged["_confirm"]

    # same value → immediate reply, nothing staged
    outcome, reply = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "retainer_monthly", "value": "3000"})
    )
    assert outcome == "reply" and "already" in reply

    # bad field → the coercion error passes straight through
    outcome, reply = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "name", "value": "X"})
    )
    assert outcome == "reply" and "can't edit" in reply


def test_stage_add_and_remove_cities(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        slack_assistant, "_client_row", lambda cid, cols: {"target_cities": ["Austin", "Waco"]}
    )
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_cities("c1", {"cities": ["waco", "Temple"]})
    )
    assert outcome == "confirm"
    assert staged["added"] == ["Temple"] and staged["merged"] == ["Austin", "Waco", "Temple"]
    assert "Temple" in staged["_confirm"] and "already on the list" in staged["_confirm"]

    outcome, reply = asyncio.run(slack_assistant._stage_add_cities("c1", {"cities": ["austin"]}))
    assert outcome == "reply" and "nothing to add" in reply

    outcome, staged = asyncio.run(
        slack_assistant._stage_remove_cities("c1", {"cities": ["WACO"]})
    )
    assert outcome == "confirm" and staged["removed"] == ["Waco"] and staged["remaining"] == ["Austin"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_cities("c1", {"cities": ["Nowhere"]})
    )
    assert outcome == "reply" and "Austin" in reply  # lists current cities back

    outcome, reply = asyncio.run(slack_assistant._stage_add_cities("c1", {}))
    assert outcome == "reply"


def test_stage_add_goal_validates_like_the_api():
    import asyncio

    stage = slack_assistant._stage_add_goal
    # unknown type
    outcome, reply = asyncio.run(stage("c1", {"goal_type": "wat", "label": "x"}))
    assert outcome == "reply" and "Goal type" in reply
    # non-custom needs target_value
    outcome, reply = asyncio.run(stage("c1", {"goal_type": "organic_clicks", "label": "x"}))
    assert outcome == "reply" and "target value" in reply
    # keyword_position needs keyword
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "keyword_position", "label": "x", "target_value": 3})
    )
    assert outcome == "reply" and "keyword" in reply.lower()
    # keywords_in_top needs target_position
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "keywords_in_top", "label": "x", "target_value": 5})
    )
    assert outcome == "reply" and "position" in reply.lower()
    # bad due date
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "x", "target_value": 800, "due_date": "Q4"})
    )
    assert outcome == "reply" and "YYYY-MM-DD" in reply
    # valid → confirm names the goal
    outcome, staged = asyncio.run(
        stage("c1", {
            "goal_type": "keyword_position", "label": "'roof repair' to top 3",
            "target_value": 3, "keyword": "roof repair", "due_date": "2026-12-31",
        })
    )
    assert outcome == "confirm"
    assert "'roof repair' to top 3" in staged["_confirm"] and "due 2026-12-31" in staged["_confirm"]
    # numbers arriving as strings are coerced, not crashed on
    outcome, staged = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "800 clicks/mo", "target_value": "800"})
    )
    assert outcome == "confirm" and staged["target_value"] == 800.0
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "x", "target_value": "lots"})
    )
    assert outcome == "reply" and "isn't a number" in reply


def test_stage_remove_tracked_keyword_resolves_and_disambiguates(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "k1", "keyword": "roof repair"},
        {"id": "k2", "keyword": "roof repair near me"},
    ]
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: supabase)

    outcome, staged = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "roof repair"})
    )
    assert outcome == "confirm" and staged["keyword_id"] == "k1"
    assert "rank history" in staged["_confirm"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "roof"})
    )
    assert outcome == "reply" and "matches 2" in reply

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "plumber"})
    )
    assert outcome == "reply" and "roof repair" in reply


def test_stage_generate_report_wording_and_validation():
    import asyncio

    outcome, staged = asyncio.run(slack_assistant._stage_generate_report("c1", {}))
    assert outcome == "confirm"
    assert staged["report_type"] == "monthly" and staged["deliver"] is False
    assert "not delivered" in staged["_confirm"]

    outcome, staged = asyncio.run(
        slack_assistant._stage_generate_report("c1", {"report_type": "ai_visibility", "deliver": True})
    )
    assert outcome == "confirm" and "DELIVER" in staged["_confirm"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_generate_report("c1", {"report_type": "quarterly"})
    )
    assert outcome == "reply" and "Report type" in reply


def test_act_generate_report_enqueues(monkeypatch):
    from services import client_report

    calls = []
    monkeypatch.setattr(
        client_report, "enqueue_client_report",
        lambda cid, rtype, deliver=False: calls.append((cid, rtype, deliver)) or "r1",
    )
    out = slack_assistant._act_generate_report("c1", {"report_type": "weekly", "deliver": True})
    assert calls == [("c1", "weekly", True)]
    assert "delivered" in out


def test_act_add_tracked_keywords_upserts_and_enqueues(monkeypatch):
    from unittest.mock import MagicMock

    from services import keyword_market, rank_materialize

    supabase = MagicMock()
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: supabase)
    mats, markets = [], []
    monkeypatch.setattr(rank_materialize, "enqueue_materialize", lambda cid: mats.append(cid))
    monkeypatch.setattr(
        keyword_market, "enqueue_keyword_market", lambda cid, **kw: markets.append(cid)
    )
    out = slack_assistant._act_add_tracked_keywords("c1", {"new": ["roof repair", "roof leak"]})
    rows = supabase.table.return_value.upsert.call_args[0][0]
    assert [r["keyword"] for r in rows] == ["roof repair", "roof leak"]
    assert all(r["client_id"] == "c1" for r in rows)
    assert mats == ["c1"] and markets == ["c1"]
    assert "roof repair" in out

    # staged args lost → guidance, nothing written
    supabase.reset_mock()
    out = slack_assistant._act_add_tracked_keywords("c1", {})
    assert "lost track" in out and not supabase.table.called


def test_act_update_profile_website_triggers_rescrape(monkeypatch):
    from unittest.mock import MagicMock

    supabase = MagicMock()
    monkeypatch.setattr(slack_assistant, "get_supabase", lambda: supabase)
    out = slack_assistant._act_update_profile(
        "c1", {"field": "website_url", "coerced_value": "https://new.acme.com"}
    )
    updates = supabase.table.return_value.update.call_args[0][0]
    assert updates["website_url"] == "https://new.acme.com"
    assert updates["website_analysis_status"] == "pending"
    job = supabase.table.return_value.insert.call_args[0][0]
    assert job["job_type"] == "website_scrape"
    assert job["payload"]["website_url"] == "https://new.acme.com"
    assert "re-running the site analysis" in out

    # a non-website field writes only the field (no scrape job)
    supabase.reset_mock()
    out = slack_assistant._act_update_profile("c1", {"field": "is_sab", "coerced_value": True})
    updates = supabase.table.return_value.update.call_args[0][0]
    assert updates["is_sab"] is True
    assert not supabase.table.return_value.insert.called
    assert "SAB" in out


def test_admin_actions_registered_confirm_gated_and_staged():
    admin_actions = (
        "update_client_profile", "add_target_cities", "remove_target_cities",
        "add_tracked_keywords", "remove_tracked_keyword",
        "add_ai_keywords", "remove_ai_keyword", "add_ai_competitor", "remove_ai_competitor",
        "add_campaign_goal", "remove_campaign_goal", "generate_client_report",
    )
    for name in admin_actions:
        meta = slack_assistant._ACTIONS[name]
        # every admin write is confirm-gated with its own wording, and staged so
        # the confirm names the exact change before anything is written.
        assert meta["paid"] is True, name
        assert meta.get("note"), name
        assert callable(meta.get("stage")), name
        tool = next(t for t in slack_assistant._ACTION_TOOLS if t["name"] == name)
        assert tool["input_schema"]["properties"], name
