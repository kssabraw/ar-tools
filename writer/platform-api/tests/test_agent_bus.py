"""Tests for the agent coordination bus (services/agent_bus.py).

Pure helpers only: inbox filtering and the coordination-health metrics DORA reads
(stalled actionable handoffs vs informational notices, open blockers, churn loops).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import agent_bus

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _msg(**kw):
    base = {"from_agent": "sermastr", "to_agent": "pace", "kind": "handoff",
            "status": "open", "created_at": _iso(1), "correlation_id": None}
    base.update(kw)
    return base


def test_inbox_filter_addresses_and_open_only():
    msgs = [
        _msg(to_agent="pace", created_at=_iso(2)),
        _msg(to_agent="broadcast", created_at=_iso(1)),
        _msg(to_agent="sermastr", created_at=_iso(3)),
        _msg(to_agent="pace", status="acted", created_at=_iso(4)),
    ]
    got = agent_bus.inbox_filter(msgs, "pace")
    # pace + broadcast, open only, newest first.
    assert [m["created_at"] for m in got] == [_iso(1), _iso(2)]
    # With open_only False the acted one comes back too.
    assert len(agent_bus.inbox_filter(msgs, "pace", open_only=False)) == 3


def test_coordination_metrics_stalled_blockers_and_loops():
    msgs = [
        _msg(kind="handoff", created_at=_iso(72)),                 # stalled (>48h, actionable)
        _msg(kind="handoff", created_at=_iso(2)),                  # fresh, not stalled
        _msg(kind="blocker", to_agent="dora", created_at=_iso(96)),  # open blocker + stalled
        _msg(kind="notice", to_agent="dora", created_at=_iso(200)),  # old but informational → not stalled
        _msg(kind="handoff", status="acted", created_at=_iso(300)),  # closed → ignored
    ]
    m = agent_bus.coordination_metrics(msgs, now=NOW, stale_hours=48)
    stalled_kinds = sorted(s["kind"] for s in m["stalled"])
    assert stalled_kinds == ["blocker", "handoff"]          # the notice is not stalled
    assert len(m["open_blockers"]) == 1
    assert m["open"] == 4 and m["total"] == 5


def test_coordination_metrics_detects_loops():
    corr = "strategy_proposal:r1:0"
    thread = [
        _msg(correlation_id=corr, from_agent="sermastr", to_agent="pace", created_at=_iso(10)),
        _msg(correlation_id=corr, from_agent="pace", to_agent="sermastr", kind="request", created_at=_iso(8)),
        _msg(correlation_id=corr, from_agent="sermastr", to_agent="pace", created_at=_iso(6)),
    ]
    m = agent_bus.coordination_metrics(thread, now=NOW, stale_hours=48)
    assert m["loops"] and m["loops"][0]["correlation_id"] == corr
    assert m["loops"][0]["flips"] == 2


def test_coordination_metrics_no_false_loop_on_clean_handoff():
    corr = "strategy_proposal:r2:0"
    clean = [
        _msg(correlation_id=corr, from_agent="sermastr", to_agent="pace", created_at=_iso(10)),
        _msg(correlation_id=corr, from_agent="pace", to_agent="sermastr", kind="ack", created_at=_iso(9)),
    ]
    assert agent_bus.coordination_metrics(clean, now=NOW)["loops"] == []
