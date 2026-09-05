"""Unit tests for the revision-tracking pure helpers (services/revision_tracking.py)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import revision_tracking as rt  # noqa: E402

_REV = "in_review"


def _task(id_, count, status="in_progress", client_id=None, assignee=None, created_by=None, name="T", completed=False):
    return {
        "id": id_, "revision_count": count, "status_key": status, "client_id": client_id,
        "assignee_name": assignee, "created_by": created_by, "name": name, "completed": completed,
    }


def test_revision_bucket():
    assert rt.revision_bucket(0) is None
    assert rt.revision_bucket(1) == "1×"
    assert rt.revision_bucket(2) == "2×"
    assert rt.revision_bucket(3) == "3+×"
    assert rt.revision_bucket(9) == "3+×"


def test_summarize_totals_and_buckets():
    tasks = [
        _task("a", 1, client_id="c1", assignee="Ivy"),
        _task("b", 3, status=_REV, client_id="c1", assignee="Ivy"),   # currently in revision
        _task("c", 2, client_id="c2", created_by="p1", completed=True),  # revised then shipped
        _task("d", 0, client_id="c2"),                                # never revised → ignored
    ]
    r = rt.summarize_revisions(tasks, _REV, {"c1": "Acme", "c2": "Beta"}, {"p1": "Kyle"})
    assert r["total_requests"] == 6          # 1 + 3 + 2
    assert r["tasks_revised"] == 3
    assert r["repeat_revised"] == 2          # b(3) and c(2)
    assert r["in_revision_now"] == 1         # only b is in the revision status + open
    buckets = {x["bucket"]: x["count"] for x in r["by_bucket"]}
    assert buckets == {"1×": 1, "2×": 1, "3+×": 1}


def test_summarize_by_client_and_assignee_sum_counts():
    tasks = [
        _task("a", 1, client_id="c1", assignee="Ivy"),
        _task("b", 3, client_id="c1", assignee="Ivy"),
        _task("c", 2, client_id="c2", created_by="p1"),
    ]
    r = rt.summarize_revisions(tasks, _REV, {"c1": "Acme", "c2": "Beta"}, {"p1": "Kyle"})
    clients = {x["client_name"]: x["revisions"] for x in r["by_client"]}
    assert clients == {"Acme": 4, "Beta": 2}
    members = {x["member"]: x["revisions"] for x in r["by_member"]}
    assert members == {"Ivy": 4, "Kyle": 2}


def test_most_revised_sorted_and_limited():
    tasks = [_task(str(i), i, name=f"task{i}", client_id="c1") for i in range(1, 6)]
    r = rt.summarize_revisions(tasks, _REV, {"c1": "Acme"}, {}, most_revised_limit=3)
    assert [m["revision_count"] for m in r["most_revised"]] == [5, 4, 3]
    assert r["most_revised"][0]["client_name"] == "Acme"


def test_summarize_empty():
    r = rt.summarize_revisions([], _REV, {}, {})
    assert r["total_requests"] == 0 and r["tasks_revised"] == 0
    assert r["most_revised"] == [] and r["by_client"] == []
    assert all(b["count"] == 0 for b in r["by_bucket"])
