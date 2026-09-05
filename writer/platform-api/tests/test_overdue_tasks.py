"""Unit tests for the overdue-tasks pure helpers (services/overdue_tasks.py)."""

from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The service imports config.settings + db.supabase_client at load; stub the DB
# module (pure tests never touch it). config imports cleanly.
if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import overdue_tasks as ot  # noqa: E402

_EXTERNAL = {"sent_to_client"}
_TODAY = date(2026, 9, 10)


def _task(due, status="in_progress", client_id=None, assignee=None, created_by=None):
    return {
        "due_date": due, "status_key": status, "client_id": client_id,
        "assignee_name": assignee, "created_by": created_by,
    }


def test_age_bucket_boundaries():
    assert ot.age_bucket(0) is None  # due today = not overdue
    assert ot.age_bucket(-3) is None
    assert ot.age_bucket(1) == "1–2 days"
    assert ot.age_bucket(2) == "1–2 days"
    assert ot.age_bucket(3) == "3–4 days"
    assert ot.age_bucket(4) == "3–4 days"
    assert ot.age_bucket(5) == "5–6 days"
    assert ot.age_bucket(6) == "5–6 days"
    assert ot.age_bucket(7) == "7+ days"
    assert ot.age_bucket(90) == "7+ days"


def test_classify_cause():
    assert ot.classify_cause("sent_to_client", _EXTERNAL) == "external"
    assert ot.classify_cause("in_progress", _EXTERNAL) == "internal"
    assert ot.classify_cause("blocked", _EXTERNAL) == "internal"
    assert ot.classify_cause(None, _EXTERNAL) == "internal"
    # external set is configurable
    assert ot.classify_cause("blocked", {"sent_to_client", "blocked"}) == "external"


def test_summarize_buckets_and_cause_split():
    tasks = [
        _task("2026-09-09", "in_progress"),      # 1 day → 1–2, internal
        _task("2026-09-06", "sent_to_client"),   # 4 days → 3–4, external
        _task("2026-09-01", "in_progress"),      # 9 days → 7+, internal
        _task("2026-09-03", "sent_to_client"),   # 7 days → 7+, external
        _task("2026-09-15", "in_progress"),      # future → skipped (not overdue)
    ]
    r = ot.summarize_overdue(tasks, _TODAY, _EXTERNAL, {}, {})
    assert r["total"] == 4
    assert r["internal"] == 2 and r["external"] == 2
    buckets = {b["bucket"]: b for b in r["by_bucket"]}
    assert buckets["1–2 days"] == {"bucket": "1–2 days", "internal": 1, "external": 0, "total": 1}
    assert buckets["3–4 days"]["external"] == 1
    assert buckets["7+ days"] == {"bucket": "7+ days", "internal": 1, "external": 1, "total": 2}
    assert buckets["5–6 days"]["total"] == 0
    # all four buckets always present, in order
    assert [b["bucket"] for b in r["by_bucket"]] == list(ot.BUCKETS)


def test_summarize_client_and_member_resolution():
    tasks = [
        _task("2026-09-01", client_id="c1", assignee="Ivy"),
        _task("2026-09-02", client_id="c1", created_by="p1"),       # no assignee → profile
        _task("2026-09-02", client_id=None),                        # unassigned + no client
    ]
    r = ot.summarize_overdue(tasks, _TODAY, _EXTERNAL, {"c1": "Acme"}, {"p1": "Kyle"})
    clients = {c["client_name"]: c["count"] for c in r["by_client"]}
    assert clients["Acme"] == 2 and clients[ot._NO_CLIENT] == 1
    members = {m["member"]: m["count"] for m in r["by_member"]}
    assert members["Ivy"] == 1 and members["Kyle"] == 1 and members[ot._UNASSIGNED] == 1


def test_summarize_empty():
    r = ot.summarize_overdue([], _TODAY, _EXTERNAL, {}, {})
    assert r["total"] == 0
    assert all(b["total"] == 0 for b in r["by_bucket"])
    assert r["by_client"] == [] and r["by_member"] == []
