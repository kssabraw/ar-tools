"""Tests for the PACE daily digest (Phase 0B) — pure ranking + formatting.

No DB, no LLM, no emit. The runner's I/O is exercised via the pure builders it
composes; dedupe idempotency is a DB-constraint concern (integration, not here).
"""

from __future__ import annotations

from datetime import date

from services import pace_digest as D


def test_dedupe_key():
    assert D.dedupe_key(date(2026, 7, 11)) == "pace_digest:2026-07-11:portfolio"


def _client(cid, **kw):
    base = {"client_id": cid, "stale": [], "overdue": [], "unassigned": [],
            "unacted_producer": [], "month_pace": {}}
    base.update(kw)
    return base


def test_rank_orders_by_severity_and_caps():
    clients = [
        _client("c1",
                stale=[{"name": "Blocked task", "category": "blocked", "status_key": "blocked", "days": 9},
                       {"name": "Review task", "category": "in_progress", "status_key": "in_review", "days": 6}],
                overdue=[{"id": "o1"}, {"id": "o2"}, {"id": "o3"}],
                unassigned=[{"id": "u1"}],
                unacted_producer=[{"name": "Rank drop fix", "source": "rank_drop"}],
                month_pace={"behind": True}),
    ]
    items, total = D.rank_digest_items(clients, max_items=8)
    cats = [i["category"] for i in items]
    # blocked-stale (109) > other-stale (76) > overdue (63) > unacted (50)
    #   > behind_pace (40) > unassigned (20)
    assert cats == ["stale", "stale", "overdue", "unacted_producer", "behind_pace", "unassigned"]
    assert items[0]["task_name"] == "Blocked task"
    assert total == 6


def test_rank_caps_and_reports_total():
    clients = [_client("c1", overdue=[{"id": f"o{i}"} for i in range(3)]),
               _client("c2", unassigned=[{"id": "u"}]),
               _client("c3", month_pace={"behind": True})]
    items, total = D.rank_digest_items(clients, max_items=2)
    assert len(items) == 2 and total == 3
    # Highest priority first: c1 overdue (63) beats c3 behind (40) beats c2 unassigned (20)
    assert items[0]["client_id"] == "c1" and items[1]["client_id"] == "c3"


def test_format_digest_lines_and_overflow():
    items = [
        {"client_id": "c1", "category": "stale", "task_name": "GBP categories",
         "status_key": "blocked", "days": 9, "assignee_name": "Minda"},
        {"client_id": "c2", "category": "overdue", "count": 3},
    ]
    names = {"c1": "IHBS", "c2": "Acme"}
    body = D.format_digest(items, total=5, client_names=names)
    lines = body.split("\n")
    assert lines[0].startswith("• *IHBS* — “GBP categories” blocked 9d (Minda)")
    assert "@PACE unblock" in lines[0]
    assert lines[1] == "• *Acme* — 3 tasks overdue"
    assert lines[2] == "… +3 more"   # 5 total − 2 shown


def test_format_singular_overdue():
    body = D.format_digest([{"client_id": "c1", "category": "overdue", "count": 1}], 1, {"c1": "Acme"})
    assert body == "• *Acme* — 1 task overdue"
