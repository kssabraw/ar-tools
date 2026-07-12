"""Tests for PACE v1.4 morning DM briefs (§4.13)."""

from __future__ import annotations

from datetime import date

from config import settings
from services import pace_briefs as B

MONDAY = date(2026, 7, 13)


# ---------------------------------------------------------------------------
# build_brief_text (pure)
# ---------------------------------------------------------------------------
def test_brief_text_buckets_and_names():
    tasks = [
        {"id": "t1", "name": "Fix GBP", "due_date": "2026-07-10", "client_id": "c1"},   # overdue
        {"id": "t2", "name": "Blog post", "due_date": "2026-07-13", "client_id": "c2"}, # today
        {"id": "t3", "name": "Citations", "due_date": "2026-07-16", "client_id": "c1"}, # this week
        {"id": "t4", "name": "Someday", "due_date": None, "client_id": "c1"},           # no date → omitted
    ]
    text = B.build_brief_text(tasks, {"c1": "Acme", "c2": "BSA"}, MONDAY)
    assert "*Overdue:*" in text and "Fix GBP — Acme" in text
    assert "*Due today:*" in text and "Blog post — BSA" in text
    assert "*This week:*" in text and "Citations — Acme (due 2026-07-16)" in text
    assert "Someday" not in text


def test_brief_text_none_when_nothing_relevant():
    assert B.build_brief_text([], {}, MONDAY) is None
    # Only far-future / undated work → no DM (no noise).
    tasks = [{"id": "t1", "name": "Later", "due_date": "2026-09-01", "client_id": "c1"},
             {"id": "t2", "name": "Undated", "due_date": None, "client_id": "c1"}]
    assert B.build_brief_text(tasks, {}, MONDAY) is None


def test_brief_text_caps_long_buckets():
    tasks = [{"id": f"t{i}", "name": f"Task {i}", "due_date": "2026-07-10", "client_id": "c1"}
             for i in range(10)]
    text = B.build_brief_text(tasks, {"c1": "Acme"}, MONDAY)
    assert "…and 4 more" in text


# ---------------------------------------------------------------------------
# run_morning_briefs — gates
# ---------------------------------------------------------------------------
async def test_briefs_gated_off(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "pace_daily_brief_push", False)
    assert (await B.run_morning_briefs(MONDAY))["reason"] == "disabled"


async def test_briefs_skip_weekend(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "pace_daily_brief_push", True)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    assert (await B.run_morning_briefs(date(2026, 7, 18)))["reason"] == "weekend"


async def test_briefs_dedupe(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "pace_daily_brief_push", True)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(B, "_linked_members", lambda: [
        {"gid": "g1", "name": "Ivy", "profile_id": "p1", "slack_user_id": "U1"},
    ])
    monkeypatch.setattr(B.notifications, "emit", lambda **kw: None)  # already ran today
    assert (await B.run_morning_briefs(MONDAY))["reason"] == "deduped"


async def test_briefs_send_and_count_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "pace_daily_brief_push", True)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(B, "_linked_members", lambda: [
        {"gid": "g1", "name": "Ivy", "profile_id": "p1", "slack_user_id": "U1"},
        {"gid": "g2", "name": "Bo", "profile_id": None, "slack_user_id": None},  # unreachable
    ])
    emitted = {}
    monkeypatch.setattr(B.notifications, "emit", lambda **kw: emitted.update(kw) or "nid")

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "tasks":
                return _Q([{"id": "t1", "client_id": "c1", "name": "Fix GBP",
                            "due_date": "2026-07-10", "assignee_gid": "g1"}])
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(B, "get_supabase", lambda: _SB())
    sent = []

    async def fake_post(channel, text, thread_ts=None):
        sent.append((channel, text))
        return "1.2"

    monkeypatch.setattr("services.slack_assistant.post_message", fake_post)
    out = await B.run_morning_briefs(MONDAY)
    assert out == {"sent": 1, "linked": 1, "unreachable": 1}
    assert sent[0][0] == "U1" and "Fix GBP — Acme" in sent[0][1]
    assert "1 unreachable" in emitted["title"]


async def test_briefs_scope_error_logged_once_then_silent(monkeypatch):
    monkeypatch.setattr(settings, "pace_enabled", True)
    monkeypatch.setattr(settings, "pace_initiative_enabled", True)
    monkeypatch.setattr(settings, "pace_daily_brief_push", True)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")
    monkeypatch.setattr(B, "_linked_members", lambda: [
        {"gid": "g1", "name": "Ivy", "profile_id": "p1", "slack_user_id": "U1"},
        {"gid": "g2", "name": "Bo", "profile_id": "p2", "slack_user_id": "U2"},
    ])
    monkeypatch.setattr(B.notifications, "emit", lambda **kw: "nid")

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _SB:
        def table(self, name):
            if name == "tasks":
                return _Q([
                    {"id": "t1", "client_id": "c1", "name": "A", "due_date": "2026-07-10", "assignee_gid": "g1"},
                    {"id": "t2", "client_id": "c1", "name": "B", "due_date": "2026-07-10", "assignee_gid": "g2"},
                ])
            if name == "clients":
                return _Q([{"id": "c1", "name": "Acme"}])
            return _Q([])

    monkeypatch.setattr(B, "get_supabase", lambda: _SB())
    calls = []

    async def scope_fail(channel, text, thread_ts=None):
        calls.append(channel)
        raise RuntimeError("slack_error: missing_scope")

    monkeypatch.setattr("services.slack_assistant.post_message", scope_fail)
    B._scope_warning_logged = False
    out = await B.run_morning_briefs(MONDAY)
    # First scope failure stops the whole run — no per-member error storm.
    assert out["sent"] == 0 and len(calls) == 1
    assert B._scope_warning_logged is True
    B._scope_warning_logged = False
