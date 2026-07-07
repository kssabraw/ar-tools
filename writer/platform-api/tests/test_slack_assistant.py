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
