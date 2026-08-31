"""Tests for PACE Proactive Interventions (services/pace_interventions.py).

Pure: name normalization, plan fingerprinting, duplicate grouping +
disambiguation renames, the lifecycle decision (decide_scan_action), condition
parsing/application, and Slack reply/date parsing. Plus the duplicate detector's
assembly and the re-stage-then-run execution path (fake supabase + fake actions).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from config import settings
from services import pace_interventions as PI
from services.pace_auth import ActionContext


def _admin(pid="p_admin"):
    return ActionContext(profile_id=pid, role="admin", source="web")


# ---------------------------------------------------------------------------
# Pure: normalization / fingerprint / cap
# ---------------------------------------------------------------------------
def test_normalize_name_collapses_and_strips():
    assert PI.normalize_name("  GBP  Post — July! ") == "gbp post — july"
    assert PI.normalize_name("Blog Post") == PI.normalize_name("blog   post")
    assert PI.normalize_name("Task —") == PI.normalize_name("task")


def test_plan_fingerprint_order_independent_and_content_sensitive():
    a = [{"action": "reassign_task", "client_id": "c1", "args": {"task_name": "X", "assignee": "A"}},
         {"action": "reassign_task", "client_id": "c2", "args": {"task_name": "Y", "assignee": "B"}}]
    assert PI.plan_fingerprint(a) == PI.plan_fingerprint(list(reversed(a)))
    b = [dict(a[0], args={"task_name": "X", "assignee": "CHANGED"}), a[1]]
    assert PI.plan_fingerprint(a) != PI.plan_fingerprint(b)


def test_cap_actions():
    acts = [{"i": i} for i in range(5)]
    kept, overflow = PI.cap_actions(acts, 3)
    assert len(kept) == 3 and overflow == 2
    kept, overflow = PI.cap_actions(acts, 10)
    assert kept == acts and overflow == 0


# ---------------------------------------------------------------------------
# Pure: duplicate grouping + disambiguation
# ---------------------------------------------------------------------------
def test_group_duplicates_only_real_collisions():
    tasks = [
        {"id": "1", "name": "GBP Post"}, {"id": "2", "name": "gbp post"},
        {"id": "3", "name": "Blog"}, {"id": "4", "name": "GBP Post "},
    ]
    groups = PI.group_duplicates(tasks, min_group=2)
    assert set(groups) == {PI.normalize_name("GBP Post")}
    assert len(groups[PI.normalize_name("GBP Post")]) == 3  # the three collisions
    # A unique name never groups.
    assert PI.group_duplicates([{"id": "1", "name": "A"}, {"id": "2", "name": "B"}], 2) == {}


def test_disambiguation_keeps_primary_and_suffixes_rest():
    group = [
        {"id": "old", "name": "GBP Post", "created_at": "2026-01-01", "assignee_name": "Marcus"},
        {"id": "new", "name": "GBP Post", "created_at": "2026-02-01", "assignee_name": "Ivy"},
        {"id": "new2", "name": "GBP Post", "created_at": "2026-03-01", "assignee_name": None, "section_id": "s1"},
    ]
    renames = PI.disambiguation_renames(group, {"s1": "March 2026"})
    ids = {t["id"] for t, _ in renames}
    assert ids == {"new", "new2"}  # the earliest-created ("old") keeps its name
    by_id = {t["id"]: name for t, name in renames}
    assert by_id["new"] == "GBP Post — Ivy"          # assignee distinguisher
    assert by_id["new2"] == "GBP Post — March 2026"  # section-label fallback


def test_disambiguation_uniqueness_guard():
    # Two collide AND share an assignee → the second gets a counter suffix.
    group = [
        {"id": "a", "name": "Task", "created_at": "2026-01-01", "assignee_name": "Sam"},
        {"id": "b", "name": "Task", "created_at": "2026-02-01", "assignee_name": "Sam"},
        {"id": "c", "name": "Task", "created_at": "2026-03-01", "assignee_name": "Sam"},
    ]
    renames = PI.disambiguation_renames(group, {})
    names = [name for _, name in renames]
    assert len(set(map(PI.normalize_name, names))) == len(names)  # all distinct


# ---------------------------------------------------------------------------
# Pure: lifecycle decision
# ---------------------------------------------------------------------------
def _row(**kw):
    base = {"status": "proposed", "plan_fingerprint": "fp", "deferred_until": None,
            "decided_at": None, "updated_at": None, "created_at": "2026-08-01T00:00:00+00:00"}
    base.update(kw)
    return base


def test_decide_scan_action_lifecycle():
    today = date(2026, 8, 29)
    kw = dict(new_fingerprint="fp", deny_cooldown_days=14, reexec_cooldown_days=3)
    assert PI.decide_scan_action(None, today, **kw) == "create"
    assert PI.decide_scan_action(_row(status="proposed", plan_fingerprint="fp"), today, **kw) == "skip"
    assert PI.decide_scan_action(_row(status="proposed", plan_fingerprint="OLD"), today, **kw) == "refresh"
    assert PI.decide_scan_action(_row(status="executing"), today, **kw) == "skip"
    # deferred, still snoozed vs elapsed
    assert PI.decide_scan_action(_row(status="deferred", deferred_until="2026-09-10"), today, **kw) == "skip"
    assert PI.decide_scan_action(_row(status="deferred", deferred_until="2026-08-20"), today, **kw) == "resurface"
    # denied — cooldown window
    recent = (datetime.now(timezone.utc)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert PI.decide_scan_action(_row(status="denied", decided_at=recent), today, **kw) == "skip"
    assert PI.decide_scan_action(_row(status="denied", decided_at=old), today, **kw) == "create"
    # executed — re-execute cooldown
    assert PI.decide_scan_action(_row(status="executed", decided_at=recent), today, **kw) == "skip"
    assert PI.decide_scan_action(_row(status="executed", decided_at=old), today, **kw) == "create"
    # terminal → recurrence
    assert PI.decide_scan_action(_row(status="resolved"), today, **kw) == "create"
    assert PI.decide_scan_action(_row(status="superseded"), today, **kw) == "create"


# ---------------------------------------------------------------------------
# Pure: conditions
# ---------------------------------------------------------------------------
_ACTS = [
    {"action": "reassign_task", "client_id": "c1", "client_name": "Acme",
     "args": {"task_name": "GBP Post", "assignee": "Marcus"}},
    {"action": "reassign_task", "client_id": "c2", "client_name": "Beta Co",
     "args": {"task_name": "Blog", "assignee": "Ivy"}},
    {"action": "reassign_task", "client_id": "c1", "client_name": "Acme",
     "args": {"task_name": "Meta", "assignee": "Ivy"}},
]


def test_heuristic_conditions():
    assert PI.heuristic_conditions("cap at 2", _ACTS).get("max_actions") == 2
    assert PI.heuristic_conditions("only reassign to ivy", _ACTS).get("only_assignee") == "Ivy"
    assert PI.heuristic_conditions("skip beta co", _ACTS).get("exclude_clients") == ["Beta Co"]


def test_apply_conditions_only_assignee_and_cap_and_exclude_and_override():
    only = PI.apply_conditions(_ACTS, {"only_assignee": "Ivy"})
    assert [a["args"]["assignee"] for a in only] == ["Ivy", "Ivy"]
    excl = PI.apply_conditions(_ACTS, {"exclude_clients": ["Acme"]})
    assert {a["client_name"] for a in excl} == {"Beta Co"}
    dropped = PI.apply_conditions(_ACTS, {"drop_indexes": [1]})
    assert len(dropped) == 2 and dropped[0]["args"]["task_name"] == "Blog"
    capped = PI.apply_conditions(_ACTS, {"max_actions": 1})
    assert len(capped) == 1
    over = PI.apply_conditions(_ACTS, {"assignee_overrides": {"GBP Post": "Dana"}})
    assert over[0]["args"]["assignee"] == "Dana"


def test_parse_conditions_falls_back_to_heuristic_without_llm(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    d = asyncio.run(PI.parse_conditions("cap at 1", _ACTS))
    assert d.get("max_actions") == 1


# ---------------------------------------------------------------------------
# Pure: Slack reply + date parsing
# ---------------------------------------------------------------------------
def test_parse_intervention_reply_shapes():
    a = PI.parse_intervention_reply("approve 2")
    assert a["disposition"] == "approve" and a["index"] == 2 and a["code"] is None
    assert PI.parse_intervention_reply("deny 1")["disposition"] == "deny"
    assert PI.parse_intervention_reply("dismiss 3")["disposition"] == "deny"
    d = PI.parse_intervention_reply("defer 4 to 2026-09-05")
    assert d["disposition"] == "defer" and d["until_text"] == "to 2026-09-05"
    c = PI.parse_intervention_reply("approve 2 but only reassign to Ivy")
    assert c["disposition"] == "conditions" and "only reassign to Ivy" in c["conditions"]
    assert PI.parse_intervention_reply("what's on my plate") is None
    # 'everything' is neither a small index nor a hex code → not a disposition
    assert PI.parse_intervention_reply("approve everything") is None


def test_parse_intervention_reply_short_code():
    a = PI.parse_intervention_reply("approve a1b2c3")
    assert a["disposition"] == "approve" and a["code"] == "a1b2c3" and a["index"] is None
    # a code works with a trailing constraint / defer date too
    c = PI.parse_intervention_reply("approve 4f2a but cap at 2")
    assert c["disposition"] == "conditions" and c["code"] == "4f2a"
    f = PI.parse_intervention_reply("defer a1b2c3 to 2026-09-05")
    assert f["disposition"] == "defer" and f["code"] == "a1b2c3"
    # a 6-digit all-numeric token is a code, not a (nonsensical) index
    n = PI.parse_intervention_reply("deny 123456")
    assert n["disposition"] == "deny" and n["code"] == "123456" and n["index"] is None
    # a non-hex token is rejected
    assert PI.parse_intervention_reply("approve zzzz") is None


def test_short_code_and_resolution(monkeypatch):
    assert PI.short_code("a1b2c3d4-e5f6-7890-abcd-ef0123456789") == "a1b2c3"
    assert PI.short_code("") == ""
    open_rows = [{"id": "a1b2c3d4-0000-0000-0000-000000000000"},
                 {"id": "ff9988aa-0000-0000-0000-000000000000"}]
    monkeypatch.setattr(PI, "list_interventions", lambda **k: open_rows)
    assert PI.resolve_short_code("a1b2c3") == open_rows[0]["id"]     # exact
    assert PI.resolve_short_code("ff99") == open_rows[1]["id"]       # unambiguous prefix
    assert PI.resolve_short_code("zzzzzz") is None                   # no match
    # resolve_reference prefers the durable code over the positional index
    PI._channel_index["C1"] = {1: "index-id"}
    assert PI.resolve_reference("C1", {"code": "a1b2c3", "index": 1}) == open_rows[0]["id"]
    assert PI.resolve_reference("C1", {"code": None, "index": 1}) == "index-id"
    assert PI.resolve_reference("C1", {"code": None, "index": None}) is None


def test_parse_relative_date():
    today = date(2026, 8, 29)  # a Saturday
    assert PI.parse_relative_date("to 2026-09-05", today) == date(2026, 9, 5)
    assert PI.parse_relative_date("in 3 days", today) == date(2026, 9, 1)
    assert PI.parse_relative_date("tomorrow", today) == date(2026, 8, 30)
    assert PI.parse_relative_date("next week", today) == date(2026, 9, 5)
    assert PI.parse_relative_date("garbage", today) is None
    # a weekday name lands on the next such day (never today)
    assert PI.parse_relative_date("monday", today).weekday() == 0


# ---------------------------------------------------------------------------
# Detector assembly (fake supabase)
# ---------------------------------------------------------------------------
class _Q:
    def __init__(self, data): self._d = data
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    @property
    def not_(self): return self

    def execute(self): return type("R", (), {"data": self._d})()


def test_detect_duplicate_names(monkeypatch):
    tasks = [
        {"id": "t1", "client_id": "c1", "name": "GBP Post", "assignee_name": "Marcus",
         "section_id": "s1", "created_at": "2026-01-01"},
        {"id": "t2", "client_id": "c1", "name": "gbp post", "assignee_name": "Ivy",
         "section_id": "s1", "created_at": "2026-02-01"},
        {"id": "t3", "client_id": "c1", "name": "Unique Task", "assignee_name": None,
         "section_id": "s1", "created_at": "2026-02-01"},
    ]

    class _SB:
        def table(self, name):
            if name == "tasks":
                return _Q(tasks)
            if name == "task_sections":
                return _Q([{"id": "s1", "name": "January 2026"}])
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    monkeypatch.setattr(settings, "pace_intervention_dupe_min_group", 2, raising=False)
    monkeypatch.setattr(settings, "pace_intervention_dupe_critical_count", 10, raising=False)
    monkeypatch.setattr(settings, "pace_intervention_max_actions", 25, raising=False)

    out = PI.detect_duplicate_names(date(2026, 8, 29), None, critical_only=False)
    assert len(out) == 1
    p = out[0]
    assert p["kind"] == "duplicate_names" and p["signature"] == "duplicate_names:c1"
    assert p["scope_client_id"] == "c1" and p["severity"] == "warning"
    # exactly one rename (the later of the two collisions), targeted by task_id,
    # and never the unique task.
    assert len(p["actions"]) == 1
    act = p["actions"][0]
    assert act["action"] == "rename_task" and act["args"]["task_id"] == "t2"
    assert act["args"]["new_name"] == "gbp post — Ivy"


def test_detect_duplicate_names_critical_only_skips_small(monkeypatch):
    tasks = [{"id": "t1", "client_id": "c1", "name": "A", "created_at": "2026-01-01"},
             {"id": "t2", "client_id": "c1", "name": "a", "created_at": "2026-02-01"}]

    class _SB:
        def table(self, name):
            return _Q(tasks if name == "tasks" else
                      ([{"id": "c1", "name": "Acme"}] if name == "clients" else []))

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    monkeypatch.setattr(settings, "pace_intervention_dupe_critical_count", 10, raising=False)
    # critical_only pass ignores a 2-task (non-severe) collision.
    assert PI.detect_duplicate_names(date(2026, 8, 29), None, critical_only=True) == []


# ---------------------------------------------------------------------------
# Execution: re-stage then run (fake PACE_ACTIONS)
# ---------------------------------------------------------------------------
def test_execute_actions_restages_skips_and_runs(monkeypatch):
    ran_ids = []

    def _stage_ok(ctx, cid, args):
        return "confirm", {**args, "_confirm": "x", "_requester": None}

    def _run_ok(ctx, cid, args):
        ran_ids.append(args.get("task_name"))
        return f"✅ did {args.get('task_name')}"

    def _stage_reply(ctx, cid, args):
        return "reply", "target moved — nothing to do"

    fake_actions = {
        "reassign_task": {"stage": _stage_ok, "run": _run_ok},
        "nudge_assignee": {"stage": _stage_reply, "run": _run_ok},
    }
    monkeypatch.setattr(PI, "PACE_ACTIONS", fake_actions)

    actions = [
        {"action": "reassign_task", "client_id": "c1", "args": {"task_name": "X", "assignee": "A"}},
        {"action": "nudge_assignee", "client_id": "c1", "args": {"task_name": "Y"}},
        {"action": "unknown_thing", "client_id": "c1", "args": {}},
    ]
    result = asyncio.run(PI._execute_actions(actions, _admin()))
    assert ran_ids == ["X"]                    # only the staged-OK one ran
    assert len(result["ran"]) == 1
    assert len(result["skipped"]) == 2         # the 'reply' + the unknown action
    assert result["failed"] == []


# ---------------------------------------------------------------------------
# dispose(): permission gate
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Slack preview (render_plan_preview) + channel index
# ---------------------------------------------------------------------------
def test_render_plan_preview_lists_every_action_and_asks_for_yes():
    acts = [
        {"action": "reassign_task", "client_name": "Acme", "reason": "move “GBP Post” (3h) → Ivy"},
        {"action": "reassign_task", "client_name": "Beta Co", "reason": "move “Blog” (2h) → Sam"},
        {"action": "reassign_task", "client_name": "Acme", "reason": "move “Meta” (1h) → Ivy"},
    ]
    row = {"title": "Marcus is overloaded (293%)", "problem": "Way over capacity.",
           "plan": {"actions": acts, "overflow": 2}}
    txt = PI.render_plan_preview(row, "approve", None)
    assert "I'll make these 3 changes" in txt
    assert "1. move “GBP Post” (3h) → Ivy" in txt and "Blog" in txt
    assert "2 more held" in txt          # overflow surfaced
    assert "Reply *yes* to run all of them" in txt


def test_render_plan_preview_conditions_and_no_actions():
    with_cond = PI.render_plan_preview({"title": "T", "problem": "P", "plan": {"actions": _ACTS}},
                                       "conditions", "only reassign to Ivy")
    assert "only reassign to Ivy" in with_cond
    none = PI.render_plan_preview({"title": "T", "problem": "P", "plan": {"actions": []}}, "approve", None)
    assert "no automated fix" in none.lower() and "acknowledge" in none.lower()


def test_resolve_channel_index(monkeypatch):
    PI._channel_index["C1"] = {1: "id-a", 2: "id-b"}
    assert PI.resolve_channel_index("C1", 2) == "id-b"
    assert PI.resolve_channel_index("C1", 9) is None
    assert PI.resolve_channel_index("nope", 1) is None


# ---------------------------------------------------------------------------
# Per-client notes: the digest leaves a note on each affected client (in-app)
# ---------------------------------------------------------------------------
def test_emit_digest_leaves_per_client_notes(monkeypatch):
    calls = []
    monkeypatch.setattr(PI.notifications, "emit",
                        lambda **kw: calls.append(kw) or "nid")
    monkeypatch.setattr(settings, "pace_slack_channel", "C_PACE", raising=False)
    surfaced = [
        # client WITH its own channel → per-client note routes there (no skip)
        {"id": "iv1", "severity": "warning", "title": "Acme dupes", "problem": "dupe names",
         "scope_client_id": "client-acme", "created_at": "2026-08-01",
         "plan": {"actions": [{"reason": "rename x"}]}},
        # client WITHOUT a channel → per-client note is in-app only (skip slack)
        {"id": "iv2", "severity": "warning", "title": "Beta overdue", "problem": "overdue",
         "scope_client_id": "client-beta", "created_at": "2026-08-02",
         "plan": {"actions": [{"reason": "nudge y"}]}},
        # cross-client (member_overload) → NO per-client note
        {"id": "iv3", "severity": "critical", "title": "Marcus overloaded", "problem": "293%",
         "scope_client_id": None, "created_at": "2026-08-03",
         "plan": {"actions": [{"reason": "move z"}]}},
    ]

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "pace_interventions":
                return _Q(surfaced)                 # the open set for the reply index
            if name == "clients":
                return _Q([{"id": "client-acme", "slack_channel_id": "C_ACME"},
                           {"id": "client-beta", "slack_channel_id": None}])
            return _Q([])

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    PI._emit_digest(surfaced, date(2026, 8, 29))

    portfolio = [c for c in calls if c.get("client_id") is None and c["kind"] == "pace_intervention"]
    acme = [c for c in calls if c.get("client_id") == "client-acme"]
    beta = [c for c in calls if c.get("client_id") == "client-beta"]
    assert len(portfolio) == 1
    # client WITH a channel → routed there (no skip_channels)
    assert len(acme) == 1 and "skip_channels" not in acme[0]["payload"]
    # client WITHOUT a channel → in-app only
    assert len(beta) == 1 and beta[0]["payload"].get("skip_channels") == ["slack"]
    # the cross-client overload (iv3) got NO per-client note
    assert not any(c.get("client_id") == "iv3" or c.get("client_id") == "client-none" for c in calls)
    assert all(c.get("client_id") in (None, "client-acme", "client-beta") for c in calls)
    # per-client dedupe_key includes the date so a resurface re-notes
    assert acme[0]["dedupe_key"] == "pace_intervention_client:iv1:2026-08-29"
    # reply index is over the full open set, stable-ordered by created_at (asc), not severity
    assert PI._channel_index.get("C_PACE") == {1: "iv1", 2: "iv2", 3: "iv3"}


def test_dispose_permission_refused_for_low_role():
    va = ActionContext(profile_id="p", role="team_member", source="web")
    out = asyncio.run(PI.dispose("id123", va, "approve"))
    assert out["ok"] is False and out["status"] is None and out["code"] == "forbidden"
    anon = ActionContext(profile_id=None, role=None, source="slack")
    out2 = asyncio.run(PI.dispose("id123", anon, "deny"))
    assert out2["ok"] is False and out2["status"] is None and out2["code"] == "forbidden"


# ---------------------------------------------------------------------------
# Severe-scan throttle
# ---------------------------------------------------------------------------
def test_severe_throttle(monkeypatch):
    monkeypatch.setattr(settings, "pace_intervention_severe_min_interval_minutes", 15, raising=False)
    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(PI, "_last_severe_scan_at", None, raising=False)
    assert PI._severe_throttled(now) is False                      # never run → not throttled
    monkeypatch.setattr(PI, "_last_severe_scan_at", now - timedelta(minutes=5), raising=False)
    assert PI._severe_throttled(now) is True                       # 5 min ago < 15 → throttled
    monkeypatch.setattr(PI, "_last_severe_scan_at", now - timedelta(minutes=20), raising=False)
    assert PI._severe_throttled(now) is False                      # 20 min ago ≥ 15 → allowed
    monkeypatch.setattr(settings, "pace_intervention_severe_min_interval_minutes", 0, raising=False)
    monkeypatch.setattr(PI, "_last_severe_scan_at", now, raising=False)
    assert PI._severe_throttled(now) is False                      # 0 → never throttled


# ---------------------------------------------------------------------------
# _ScanCache: shared reads are fetched once
# ---------------------------------------------------------------------------
def test_scan_cache_client_names_queries_once(monkeypatch):
    hits = []
    monkeypatch.setattr(PI, "_client_names",
                        lambda ids: hits.append(sorted(ids)) or {i: f"name-{i}" for i in ids})
    cache = PI._ScanCache()
    assert cache.client_names(["a", "b"]) == {"a": "name-a", "b": "name-b"}
    # a second call for an already-seen id does NOT re-query it; a new id does
    cache.client_names(["a", "c"])
    assert hits == [["a", "b"], ["c"]]


# ---------------------------------------------------------------------------
# _approve: atomic claim + all-skipped → re-opened (not falsely "executed")
# ---------------------------------------------------------------------------
def _fake_sb_capture():
    updates = []

    class _Q:
        def __init__(self, data, sink=None): self._d = data; self._sink = sink; self._payload = None
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def update(self, payload, *a, **k): self._payload = payload; return self
        def execute(self):
            if self._payload is not None and self._sink is not None:
                self._sink.append(self._payload)
            return type("R", (), {"data": self._d})()

    return updates, _Q


def test_approve_lost_claim_bails(monkeypatch):
    updates, _Q = _fake_sb_capture()

    class _SB:
        def table(self, name):
            # the conditional claim UPDATE ... WHERE status=prior matched 0 rows
            return _Q([], updates)

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    row = {"id": "iv1", "status": "proposed", "title": "T",
           "plan": {"actions": [{"action": "reassign_task", "client_id": "c", "args": {}}]}}
    out = asyncio.run(PI._approve(row, _admin(), conditions=None))
    assert out["ok"] is False and out["status"] == "executing"
    assert "someone else" in out["message"]


def test_approve_all_skipped_reopens(monkeypatch):
    updates, _Q = _fake_sb_capture()

    class _SB:
        def table(self, name):
            return _Q([{"id": "iv1"}], updates)          # claim succeeds (non-empty)

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    # every action stages a refusal → all skipped, none ran/failed
    monkeypatch.setattr(PI, "PACE_ACTIONS",
                        {"rename_task": {"stage": lambda *a: ("reply", "already handled"),
                                         "run": lambda *a: "unused"}})
    row = {"id": "iv1", "status": "proposed", "title": "Acme dupes",
           "plan": {"actions": [{"action": "rename_task", "client_id": "c", "args": {"task_id": "t1"}}]}}
    out = asyncio.run(PI._approve(row, _admin(), conditions=None))
    assert out["ok"] is False and out["status"] == "proposed"      # re-opened, NOT "executed"
    assert "left it open" in out["message"]
    # the final status write set status back to proposed
    assert updates[-1].get("status") == "proposed"


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------
def test_summarize_week():
    open_rows = [{"id": "a", "kind": "member_overload", "severity": "critical", "title": "X"},
                 {"id": "b", "kind": "duplicate_names", "severity": "warning", "title": "Y"}]
    decided = [{"disposition": "approved", "result": {"ran": ["1", "2"], "skipped": ["s"], "failed": []}},
               {"disposition": "denied", "result": None},
               {"disposition": "deferred", "result": None}]
    s = PI.summarize_week(open_rows, decided, 3)
    assert s["open_total"] == 2 and s["open_by_severity"]["critical"] == 1
    assert s["dispositions"] == {"approved": 1, "denied": 1, "deferred": 1}
    assert s["executed"] == {"ran": 2, "skipped": 1, "failed": 0}
    assert s["resolved"] == 3


def test_render_weekly_report_content_and_quiet():
    today = date(2026, 9, 4)  # a Friday
    open_rows = [{"id": "a1b2c3d4-0000-0000-0000-000000000000", "severity": "critical",
                  "title": "Marcus overloaded"}]
    stats = PI.summarize_week(open_rows,
                              [{"disposition": "approved",
                                "result": {"ran": ["1"], "skipped": [], "failed": []}}], 0)
    body = PI.render_weekly_report(stats, open_rows, today)
    assert body and "1 open" in body and "a1b2c3" in body and "1 approved" in body
    # a totally-quiet week → nothing to post
    assert PI.render_weekly_report(PI.summarize_week([], [], 0), [], today) is None


def test_run_weekly_report_gated(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", False, raising=False)
    assert PI.run_weekly_report(date(2026, 9, 4))["posted"] is False
    monkeypatch.setattr(settings, "pace_enabled", True, raising=False)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True, raising=False)
    monkeypatch.setattr(settings, "pace_interventions_enabled", True, raising=False)
    monkeypatch.setattr(settings, "pace_intervention_report_enabled", False, raising=False)
    out = PI.run_weekly_report(date(2026, 9, 4))
    assert out["posted"] is False and out["reason"] == "report_disabled"


def test_run_weekly_report_posts(monkeypatch):
    for f in ("pace_enabled", "pace_initiative_enabled", "pace_interventions_enabled",
              "pace_intervention_report_enabled"):
        monkeypatch.setattr(settings, f, True, raising=False)
    emitted = []
    monkeypatch.setattr(PI.notifications, "emit", lambda **kw: emitted.append(kw) or "nid")
    seq = iter([
        [{"id": "a1b2c3d4-0000-0000-0000-000000000000", "kind": "member_overload",
          "severity": "critical", "title": "Marcus overloaded", "status": "proposed"}],  # open
        [{"disposition": "approved", "result": {"ran": ["x"], "skipped": [], "failed": []},
          "decided_at": "2026-09-02"}],                                                    # decided
        [],                                                                                # resolved
    ])

    class _Q:
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def gte(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": next(seq)})()

    class _SB:
        def table(self, name): return _Q()

    monkeypatch.setattr(PI, "get_supabase", lambda: _SB())
    out = PI.run_weekly_report(date(2026, 9, 4))
    assert out["posted"] is True and out["open"] == 1
    assert emitted and emitted[0]["kind"] == "pace_intervention_report"
    assert emitted[0]["dedupe_key"].startswith("pace_intervention_report:")
    assert emitted[0]["severity"] == "warning"  # a critical is open
