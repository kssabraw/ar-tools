"""Unit tests for the Everhour Phase 2 task mirror (services/everhour_sync).

Pure helpers + gating + the enqueue/mirror/backfill flows with a fake Supabase
(no live network — everhour_service.create_task is mocked). Mirrors the suite
convention: pure logic exhaustively, DB/HTTP mocked.

docs/modules/everhour-time-tracking-integration-plan-v1_0.md §3.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from config import settings
from services import everhour_sync


# ---------------------------------------------------------------------------
# A minimal projection-agnostic fake Supabase query builder.
# ---------------------------------------------------------------------------
class _Query:
    def __init__(self, table: str, store: "_Store"):
        self._table = table
        self._store = store
        self._mode = "select"  # select | insert | update
        self._payload = None

    # supabase-py exposes `.not_` as a property returning a filter builder —
    # `.not_.is_(col, "null")`; filters are no-ops in the fake, so return self.
    @property
    def not_(self):
        return self

    # terminal-chainable filter no-ops
    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, **k):
        self._mode = "upsert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def execute(self):
        if self._mode in ("insert", "upsert"):
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            log = self._store.upserts if self._mode == "upsert" else self._store.inserts
            log.setdefault(self._table, []).extend(rows)
            # An upsert feeds the reads so a later recompute sees what was
            # written (models the real round-trip); inserts don't.
            if self._mode == "upsert":
                self._store.reads.setdefault(self._table, []).extend(rows)
            returned = [
                {**r, "id": r.get("id") or f"{self._table}-{i}"}
                for i, r in enumerate(rows)
            ]
            return type("R", (), {"data": returned})()
        if self._mode == "update":
            self._store.updates.setdefault(self._table, []).append(self._payload)
            return type("R", (), {"data": []})()
        return type("R", (), {"data": list(self._store.reads.get(self._table, []))})()


class _Store:
    def __init__(self, reads=None):
        self.reads = reads or {}
        self.inserts: dict[str, list] = {}
        self.upserts: dict[str, list] = {}
        self.updates: dict[str, list] = {}

    def table(self, name):
        return _Query(name, self)


def _open_gate(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", True)
    monkeypatch.setattr(settings, "everhour_mirror_enabled", True)
    monkeypatch.setattr(settings, "everhour_api_key", "sk_test")


# ---------------------------------------------------------------------------
# should_mirror (pure)
# ---------------------------------------------------------------------------
def test_should_mirror_eligible():
    assert everhour_sync.should_mirror(
        {"id": "t1", "client_id": "c1", "parent_task_id": None,
         "everhour_task_id": None, "deleted_at": None}
    ) is True


def test_should_mirror_rejects_subtask():
    assert everhour_sync.should_mirror(
        {"id": "s1", "client_id": "c1", "parent_task_id": "t1",
         "everhour_task_id": None, "deleted_at": None}
    ) is False


def test_should_mirror_rejects_clientless():
    assert everhour_sync.should_mirror(
        {"id": "t1", "client_id": None, "parent_task_id": None}
    ) is False


def test_should_mirror_rejects_already_mirrored():
    assert everhour_sync.should_mirror(
        {"id": "t1", "client_id": "c1", "parent_task_id": None,
         "everhour_task_id": "ev:9", "deleted_at": None}
    ) is False


def test_should_mirror_rejects_trashed():
    assert everhour_sync.should_mirror(
        {"id": "t1", "client_id": "c1", "parent_task_id": None,
         "everhour_task_id": None, "deleted_at": "2026-08-29T00:00:00Z"}
    ) is False


def test_should_mirror_none_and_missing_id():
    assert everhour_sync.should_mirror(None) is False
    assert everhour_sync.should_mirror({"client_id": "c1"}) is False


# ---------------------------------------------------------------------------
# mirror_user_id (pure — plan §12 gotcha #5: stored text -> int)
# ---------------------------------------------------------------------------
def test_mirror_user_id_casts_text_to_int():
    assert everhour_sync.mirror_user_id("1304") == 1304
    assert everhour_sync.mirror_user_id(1304) == 1304


def test_mirror_user_id_none_blank_nonnumeric():
    assert everhour_sync.mirror_user_id(None) is None
    assert everhour_sync.mirror_user_id("") is None
    assert everhour_sync.mirror_user_id("   ") is None
    assert everhour_sync.mirror_user_id("ev:12") is None  # not an int


# ---------------------------------------------------------------------------
# mirror_gate_open
# ---------------------------------------------------------------------------
def test_mirror_gate_requires_all_three(monkeypatch):
    _open_gate(monkeypatch)
    assert everhour_sync.mirror_gate_open() is True
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.mirror_gate_open() is False
    monkeypatch.setattr(settings, "everhour_enabled", True)
    monkeypatch.setattr(settings, "everhour_mirror_enabled", False)
    assert everhour_sync.mirror_gate_open() is False
    monkeypatch.setattr(settings, "everhour_mirror_enabled", True)
    monkeypatch.setattr(settings, "everhour_api_key", "")
    assert everhour_sync.mirror_gate_open() is False


# ---------------------------------------------------------------------------
# enqueue_mirror
# ---------------------------------------------------------------------------
_TASK = {"id": "t1", "client_id": "c1", "parent_task_id": None,
         "everhour_task_id": None, "deleted_at": None}


def test_enqueue_mirror_noop_when_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    store = _Store()
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    everhour_sync.enqueue_mirror(_TASK)
    assert store.inserts == {}


def test_enqueue_mirror_noop_when_ineligible(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store()
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    everhour_sync.enqueue_mirror({**_TASK, "parent_task_id": "p"})  # subtask
    assert store.inserts == {}


def test_enqueue_mirror_inserts_job(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"async_jobs": []})  # no in-flight job
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    everhour_sync.enqueue_mirror(_TASK)
    jobs = store.inserts.get("async_jobs")
    assert jobs and jobs[0]["job_type"] == "everhour_mirror"
    assert jobs[0]["entity_id"] == "t1"
    assert jobs[0]["payload"] == {"task_id": "t1", "client_id": "c1"}


def test_enqueue_mirror_dedupes_in_flight(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"async_jobs": [{"id": "job-existing"}]})
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    everhour_sync.enqueue_mirror(_TASK)
    assert store.inserts == {}  # a mirror is already queued for this task


def test_enqueue_mirror_never_raises(monkeypatch):
    _open_gate(monkeypatch)

    class _Boom:
        def table(self, name):
            raise RuntimeError("db down")

    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: _Boom())
    everhour_sync.enqueue_mirror(_TASK)  # swallowed, logged — no raise


# ---------------------------------------------------------------------------
# mirror_task
# ---------------------------------------------------------------------------
async def test_mirror_task_success_stamps_join_key(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "tasks": [{"id": "t1", "client_id": "c1", "parent_task_id": None,
                       "name": "40 Citations", "assignee_id": "m1",
                       "everhour_task_id": None, "deleted_at": None}],
            "clients": [{"everhour_project_id": "ev:proj"}],
            "asana_team_members": [{"everhour_user_id": "1304"}],
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch(
        "services.everhour_service.create_task",
        new=AsyncMock(return_value={"id": "ev:task9"}),
    ) as create:
        result = await everhour_sync.mirror_task("t1")
    assert result == {"status": "mirrored", "everhour_task_id": "ev:task9"}
    # the assignee was cast to an int userId in the payload (gotcha #5)
    _, args, kwargs = create.mock_calls[0]
    assert args[0] == "ev:proj"
    assert args[1] == {"name": "40 Citations", "assignees": [{"userId": 1304}]}
    # the join key was stamped back on the task
    upd = store.updates.get("tasks")
    assert upd and upd[0]["everhour_task_id"] == "ev:task9"
    assert "everhour_synced_at" in upd[0]


async def test_mirror_task_skips_when_no_project(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "tasks": [{"id": "t1", "client_id": "c1", "parent_task_id": None,
                       "name": "x", "assignee_id": None,
                       "everhour_task_id": None, "deleted_at": None}],
            "clients": [{"everhour_project_id": None}],  # unmapped
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch("services.everhour_service.create_task", new=AsyncMock()) as create:
        result = await everhour_sync.mirror_task("t1")
    assert result == {"status": "skipped", "reason": "no_project"}
    create.assert_not_awaited()
    assert store.updates == {}


async def test_mirror_task_idempotent_already_mirrored(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "tasks": [{"id": "t1", "client_id": "c1", "parent_task_id": None,
                       "name": "x", "everhour_task_id": "ev:already",
                       "deleted_at": None}],
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch("services.everhour_service.create_task", new=AsyncMock()) as create:
        result = await everhour_sync.mirror_task("t1")
    assert result == {"status": "skipped", "reason": "already_mirrored"}
    create.assert_not_awaited()


async def test_mirror_task_no_id_from_everhour_does_not_stamp(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "tasks": [{"id": "t1", "client_id": "c1", "parent_task_id": None,
                       "name": "x", "assignee_id": None,
                       "everhour_task_id": None, "deleted_at": None}],
            "clients": [{"everhour_project_id": "ev:proj"}],
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch(
        "services.everhour_service.create_task", new=AsyncMock(return_value={})
    ):
        result = await everhour_sync.mirror_task("t1")
    assert result == {"status": "failed", "reason": "no_everhour_task_id"}
    assert store.updates == {}  # never stamp a bogus join key


async def test_mirror_task_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    result = await everhour_sync.mirror_task("t1")
    assert result == {"status": "skipped", "reason": "gate_closed"}


# ---------------------------------------------------------------------------
# backfill_mirror
# ---------------------------------------------------------------------------
def test_backfill_mirror_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.backfill_mirror()["status"] == "skipped"


def test_backfill_mirror_no_mapped_clients(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"clients": []})
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    out = everhour_sync.backfill_mirror()
    assert out == {"status": "ok", "reason": "no_mapped_clients", "candidates": 0, "enqueued": 0}


def test_backfill_mirror_enqueues_and_skips_in_flight(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "clients": [{"id": "c1"}],
            "tasks": [{"id": "t1", "client_id": "c1"},
                      {"id": "t2", "client_id": "c1"}],
            "async_jobs": [{"entity_id": "t1"}],  # t1 already queued
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    out = everhour_sync.backfill_mirror()
    assert out["candidates"] == 2
    assert out["enqueued"] == 1
    jobs = store.inserts.get("async_jobs")
    assert [j["entity_id"] for j in jobs] == ["t2"]
    assert "scheduled_at" in jobs[0]


# ===========================================================================
# Phase 3 — time pull + rollups
# ===========================================================================
from datetime import date  # noqa: E402


# ---------------------------------------------------------------------------
# Pure rollups
# ---------------------------------------------------------------------------
def test_rollup_by_task_sums_and_skips_none():
    entries = [
        {"task_id": "t1", "seconds": 3600},
        {"task_id": "t1", "seconds": 1800},
        {"task_id": "t2", "seconds": 600},
        {"task_id": None, "seconds": 999},   # ad-hoc — excluded
        {"task_id": "t3", "seconds": None},  # malformed — excluded
    ]
    assert everhour_sync.rollup_by_task(entries) == {"t1": 5400, "t2": 600}


def test_rollup_by_client_and_member():
    entries = [
        {"client_id": "c1", "member_id": "m1", "seconds": 100},
        {"client_id": "c1", "member_id": "m2", "seconds": 50},
        {"client_id": None, "member_id": "m1", "seconds": 25},  # internal time
    ]
    assert everhour_sync.rollup_by_client(entries) == {"c1": 150}
    # ad-hoc/internal time still counts toward member utilization
    assert everhour_sync.rollup_by_member(entries) == {"m1": 125, "m2": 50}


def test_rollup_empty():
    assert everhour_sync.rollup_by_task([]) == {}
    assert everhour_sync.rollup_by_client(None) == {}


# ---------------------------------------------------------------------------
# sync_window
# ---------------------------------------------------------------------------
def test_sync_window():
    assert everhour_sync.sync_window(date(2026, 8, 29), 14) == ("2026-08-15", "2026-08-29")
    assert everhour_sync.sync_window(date(2026, 8, 29), 0) == ("2026-08-29", "2026-08-29")


# ---------------------------------------------------------------------------
# resolve_time_entries (pure — the join logic)
# ---------------------------------------------------------------------------
def test_resolve_native_task_uses_task_client_authoritatively():
    parsed = [{
        "everhour_record_id": "11", "everhour_task_id": "ev:taskA",
        "everhour_project_id": "ev:projX",  # differs from the task's client's project
        "everhour_user_id": "1304", "entry_date": "2026-08-20",
        "seconds": 3600, "billable": None, "comment": None,
    }]
    rows = everhour_sync.resolve_time_entries(
        parsed,
        tasks_by_eh={"ev:taskA": {"id": "task-A", "client_id": "client-A"}},
        clients_by_project={"ev:projX": "client-X"},  # must be ignored for a matched task
        members_by_eh={"1304": "mem-1"},
        synced_at="2026-08-29T00:00:00+00:00",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["task_id"] == "task-A"
    assert r["client_id"] == "client-A"  # the task's client, NOT the record's project client
    assert r["member_id"] == "mem-1"
    assert r["seconds"] == 3600
    assert r["everhour_record_id"] == "11"


def test_resolve_ad_hoc_uses_project_client():
    parsed = [{
        "everhour_record_id": "12", "everhour_task_id": "ev:taskZ",  # not a native mirror
        "everhour_project_id": "ev:projB", "everhour_user_id": "1304",
        "entry_date": "2026-08-21", "seconds": 1800, "billable": True, "comment": "x",
    }]
    rows = everhour_sync.resolve_time_entries(
        parsed,
        tasks_by_eh={},  # no native match
        clients_by_project={"ev:projB": "client-B"},
        members_by_eh={"1304": "mem-1"},
        synced_at="s",
    )
    assert rows[0]["task_id"] is None
    assert rows[0]["client_id"] == "client-B"
    assert rows[0]["billable"] is True


def test_resolve_internal_time_no_client():
    # No native task AND no mapped project → internal/overhead time: kept (for
    # member utilization) but client_id None (excluded from client rollups).
    parsed = [{
        "everhour_record_id": "13", "everhour_task_id": None,
        "everhour_project_id": "ev:unmapped", "everhour_user_id": "1304",
        "entry_date": "2026-08-21", "seconds": 600, "billable": None, "comment": None,
    }]
    rows = everhour_sync.resolve_time_entries(
        parsed, tasks_by_eh={}, clients_by_project={},
        members_by_eh={"1304": "mem-1"}, synced_at="s",
    )
    assert rows[0]["task_id"] is None
    assert rows[0]["client_id"] is None
    assert rows[0]["member_id"] == "mem-1"


def test_resolve_unlinked_member():
    parsed = [{
        "everhour_record_id": "14", "everhour_task_id": "ev:taskA",
        "everhour_project_id": None, "everhour_user_id": "9999",  # not roster-linked
        "entry_date": "2026-08-21", "seconds": 600, "billable": None, "comment": None,
    }]
    rows = everhour_sync.resolve_time_entries(
        parsed, tasks_by_eh={"ev:taskA": {"id": "task-A", "client_id": "client-A"}},
        clients_by_project={}, members_by_eh={}, synced_at="s",
    )
    assert rows[0]["member_id"] is None


# ---------------------------------------------------------------------------
# sync_gate_open — reads do NOT require everhour_mirror_enabled
# ---------------------------------------------------------------------------
def test_sync_gate_ignores_mirror_flag(monkeypatch):
    _open_gate(monkeypatch)
    assert everhour_sync.sync_gate_open() is True
    monkeypatch.setattr(settings, "everhour_mirror_enabled", False)
    assert everhour_sync.sync_gate_open() is True  # mirror flag is write-only
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.sync_gate_open() is False
    monkeypatch.setattr(settings, "everhour_enabled", True)
    monkeypatch.setattr(settings, "everhour_api_key", "")
    assert everhour_sync.sync_gate_open() is False


# ---------------------------------------------------------------------------
# enqueue_everhour_sync / enqueue_due_everhour_sync
# ---------------------------------------------------------------------------
def test_enqueue_sync_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.enqueue_everhour_sync() == {"status": "skipped", "reason": "gate_closed"}


def test_enqueue_sync_dedupes_in_flight(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"async_jobs": [{"id": "j1"}]})
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    assert everhour_sync.enqueue_everhour_sync() == {"status": "skipped", "reason": "already_queued"}
    assert store.inserts == {}


def test_enqueue_sync_queues(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"async_jobs": []})
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    out = everhour_sync.enqueue_everhour_sync()
    assert out["status"] == "queued"
    assert out["job_id"]
    jobs = store.inserts.get("async_jobs")
    assert jobs and jobs[0]["job_type"] == "everhour_sync"
    assert jobs[0]["payload"] == {}


def test_enqueue_due_returns_count(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(reads={"async_jobs": []})
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    assert everhour_sync.enqueue_due_everhour_sync() == 1
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.enqueue_due_everhour_sync() == 0


# ---------------------------------------------------------------------------
# run_everhour_sync (flow)
# ---------------------------------------------------------------------------
async def test_run_sync_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    out = await everhour_sync.run_everhour_sync()
    assert out == {"status": "skipped", "reason": "gate_closed"}


async def test_run_sync_no_records(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store()
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch("services.everhour_service.list_team_time", new=AsyncMock(return_value=[])):
        out = await everhour_sync.run_everhour_sync()
    assert out["status"] == "ok"
    assert out["records"] == 0 and out["upserted"] == 0 and out["tasks_updated"] == 0
    assert store.upserts == {} and store.updates == {}


async def test_run_sync_full_flow(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "tasks": [{"id": "task-A", "client_id": "client-A", "everhour_task_id": "ev:taskA"}],
            "clients": [{"id": "client-B", "everhour_project_id": "ev:projB"}],
            "asana_team_members": [{"id": "mem-1", "everhour_user_id": "1304"}],
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    raw = [
        {"id": 11, "time": 3600, "user": 1304, "date": "2026-08-20",
         "task": {"id": "ev:taskA", "projects": ["ev:projX"]}},   # native
        {"id": 12, "time": 1800, "user": 1304, "date": "2026-08-21",
         "task": {"id": "ev:taskZ", "projects": ["ev:projB"]}},   # ad-hoc → project client
    ]
    with patch("services.everhour_service.list_team_time", new=AsyncMock(return_value=raw)):
        out = await everhour_sync.run_everhour_sync()
    assert out["records"] == 2 and out["upserted"] == 2 and out["tasks_updated"] == 1
    entries = store.upserts["time_entries"]
    by_rid = {e["everhour_record_id"]: e for e in entries}
    assert by_rid["11"]["task_id"] == "task-A" and by_rid["11"]["client_id"] == "client-A"
    assert by_rid["12"]["task_id"] is None and by_rid["12"]["client_id"] == "client-B"
    # actual_hours recomputed only for the matched task (3600s → 1.0h)
    assert store.updates["tasks"] == [{"actual_hours": 1.0}]


async def test_run_sync_delete_to_zero(monkeypatch):
    # Everhour models a delete as time:0 on the same record id — the re-read
    # zeroes the task's actual_hours, no reconciliation pass (plan §11.9).
    _open_gate(monkeypatch)
    store = _Store(
        reads={"tasks": [{"id": "task-A", "client_id": "client-A", "everhour_task_id": "ev:taskA"}]}
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    raw = [{"id": 11, "time": 0, "user": 1, "date": "2026-08-20",
            "task": {"id": "ev:taskA", "projects": []}}]
    with patch("services.everhour_service.list_team_time", new=AsyncMock(return_value=raw)):
        out = await everhour_sync.run_everhour_sync()
    assert out["upserted"] == 1
    assert store.upserts["time_entries"][0]["seconds"] == 0
    assert store.updates["tasks"] == [{"actual_hours": 0.0}]


# ---------------------------------------------------------------------------
# run_everhour_sync_job (settles the async_jobs row)
# ---------------------------------------------------------------------------
async def test_sync_job_settles_complete(monkeypatch):
    store = _Store()
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch.object(
        everhour_sync, "run_everhour_sync",
        new=AsyncMock(return_value={"status": "ok", "records": 3}),
    ):
        await everhour_sync.run_everhour_sync_job({"id": "job-1"})
    upd = store.updates["async_jobs"][0]
    assert upd["status"] == "complete"
    assert upd["result"] == {"status": "ok", "records": 3}


async def test_sync_job_settles_failed(monkeypatch):
    store = _Store()
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    with patch.object(
        everhour_sync, "run_everhour_sync", new=AsyncMock(side_effect=RuntimeError("403 boom")),
    ):
        await everhour_sync.run_everhour_sync_job({"id": "job-1"})
    upd = store.updates["async_jobs"][0]
    assert upd["status"] == "failed"
    assert "403 boom" in upd["error"]


# ===========================================================================
# Phase 4 — read surfaces (client Time card, PACE utilization)
# ===========================================================================
# ---------------------------------------------------------------------------
# billable_split (pure)
# ---------------------------------------------------------------------------
def test_billable_split_buckets():
    entries = [
        {"seconds": 3600, "billable": True},
        {"seconds": 1800, "billable": False},
        {"seconds": 600, "billable": None},   # billing not requested / unknown
        {"seconds": None, "billable": True},   # malformed — skipped
    ]
    assert everhour_sync.billable_split(entries) == {
        "billable": 3600, "non_billable": 1800, "unknown": 600
    }


def test_billable_split_empty():
    assert everhour_sync.billable_split([]) == {"billable": 0, "non_billable": 0, "unknown": 0}


# ---------------------------------------------------------------------------
# build_client_time (pure)
# ---------------------------------------------------------------------------
def test_build_client_time_totals_split_and_members():
    entries = [
        {"member_id": "m1", "seconds": 3600, "billable": True},
        {"member_id": "m1", "seconds": 1800, "billable": None},
        {"member_id": "m2", "seconds": 900, "billable": False},
    ]
    out = everhour_sync.build_client_time(
        entries, member_names={"m1": "Ivy", "m2": "Minda"}, days=30
    )
    assert out["window_days"] == 30
    assert out["total_hours"] == 1.75            # 6300s
    assert out["billable_hours"] == 1.0
    assert out["non_billable_hours"] == 0.25
    assert out["unknown_hours"] == 0.5
    # members descending by hours, named
    assert out["members"][0] == {"member_id": "m1", "name": "Ivy", "hours": 1.5}
    assert out["members"][1] == {"member_id": "m2", "name": "Minda", "hours": 0.25}


def test_build_client_time_empty():
    out = everhour_sync.build_client_time([], member_names={}, days=7)
    assert out["total_hours"] == 0.0 and out["members"] == []


# ---------------------------------------------------------------------------
# utilization_hours (pure)
# ---------------------------------------------------------------------------
def test_utilization_hours_converts():
    assert everhour_sync.utilization_hours({"m1": 7200, "m2": 1800}) == {"m1": 2.0, "m2": 0.5}
    assert everhour_sync.utilization_hours({}) == {}


# ---------------------------------------------------------------------------
# _window (pure)
# ---------------------------------------------------------------------------
def test_window_uses_default_and_override():
    frm, to, n = everhour_sync._window(None, 30)
    assert n == 30 and frm <= to
    frm2, to2, n2 = everhour_sync._window(7, 30)
    assert n2 == 7


# ---------------------------------------------------------------------------
# client_time_summary / member_utilization / client_month_actual_hours (flow)
# ---------------------------------------------------------------------------
def test_client_time_summary_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.client_time_summary("c1") == {"available": False, "reason": "not_enabled"}


def test_client_time_summary_flow(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={
            "time_entries": [
                {"member_id": "m1", "seconds": 3600, "billable": True,
                 "client_id": "c1", "task_id": "t1", "entry_date": "2026-08-20"},
            ],
            "asana_team_members": [{"id": "m1", "name": "Ivy"}],
        }
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    out = everhour_sync.client_time_summary("c1", days=30)
    assert out["available"] is True
    assert out["total_hours"] == 1.0
    assert out["members"][0]["name"] == "Ivy"


def test_member_utilization_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.member_utilization() == {}


def test_member_utilization_flow(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={"time_entries": [
            {"member_id": "m1", "seconds": 7200},
            {"member_id": "m1", "seconds": 1800},
            {"member_id": None, "seconds": 600},  # internal — still counts per-member? no member
        ]}
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    assert everhour_sync.member_utilization(7) == {"m1": 2.5}


def test_client_month_actual_hours_gate_closed(monkeypatch):
    monkeypatch.setattr(settings, "everhour_enabled", False)
    assert everhour_sync.client_month_actual_hours("c1", date(2026, 8, 1)) == 0.0


def test_client_month_actual_hours_flow(monkeypatch):
    _open_gate(monkeypatch)
    store = _Store(
        reads={"time_entries": [
            {"seconds": 3600, "client_id": "c1"},
            {"seconds": 5400, "client_id": "c1"},
        ]}
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    assert everhour_sync.client_month_actual_hours("c1", date(2026, 8, 15)) == 2.5


# ---------------------------------------------------------------------------
# _read_entries — client-scope + window filters + stable-paging order.
#
# The shared _Store fake treats eq/gte/lte as no-ops (it stores partial rows,
# which many Phase-2/3 flow tests rely on), so it can't verify that
# _read_entries actually filters — the exact "a fake more generous than the DB
# hides the bug" trap the plan §12 named. This purpose-built filtering fake
# applies the recorded predicates and records whether .order() was called
# before .range(), so it also guards the stable-paging fix (a total order is
# required or LIMIT/OFFSET paging can overlap/skip rows).
# ---------------------------------------------------------------------------
class _FilterQuery:
    def __init__(self, table, store):
        self._table, self._store = table, store
        self._eqs, self._gte, self._lte = {}, None, None
        self._ordered, self._lo, self._hi = False, 0, 10**9

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._eqs[col] = val
        return self

    def gte(self, col, val):
        self._gte = (col, val)
        return self

    def lte(self, col, val):
        self._lte = (col, val)
        return self

    def order(self, *a, **k):
        self._ordered = True
        self._store.ordered_by.append(a[0] if a else None)
        return self

    def range(self, lo, hi):
        self._lo, self._hi = lo, hi
        # An unordered .range() would page unstably — record it so the test can fail.
        if not self._ordered:
            self._store.range_without_order = True
        return self

    def execute(self):
        rows = list(self._store.reads.get(self._table, []))
        for c, v in self._eqs.items():
            rows = [r for r in rows if r.get(c) == v]
        if self._gte:
            c, v = self._gte
            rows = [r for r in rows if r.get(c) is not None and r.get(c) >= v]
        if self._lte:
            c, v = self._lte
            rows = [r for r in rows if r.get(c) is not None and r.get(c) <= v]
        return type("R", (), {"data": rows[self._lo : self._hi + 1]})()


class _FilterStore:
    def __init__(self, reads):
        self.reads = reads
        self.ordered_by: list = []
        self.range_without_order = False

    def table(self, name):
        return _FilterQuery(name, self)


def test_read_entries_scopes_client_window_and_orders(monkeypatch):
    _open_gate(monkeypatch)
    store = _FilterStore(
        reads={"time_entries": [
            {"everhour_record_id": "1", "client_id": "c1", "entry_date": "2026-08-20", "seconds": 3600},
            {"everhour_record_id": "2", "client_id": "c2", "entry_date": "2026-08-20", "seconds": 100},   # wrong client
            {"everhour_record_id": "3", "client_id": "c1", "entry_date": "2026-07-01", "seconds": 200},   # before window
            {"everhour_record_id": "4", "client_id": "c1", "entry_date": "2026-09-30", "seconds": 300},   # after window
        ]}
    )
    monkeypatch.setattr(everhour_sync, "get_supabase", lambda: store)
    rows = everhour_sync._read_entries(
        date_from="2026-08-01", date_to="2026-08-31", client_id="c1",
        cols="everhour_record_id, seconds",
    )
    # Only the in-window row for c1 — proves eq(client_id) + gte/lte(entry_date) apply.
    assert [r["everhour_record_id"] for r in rows] == ["1"]
    # And the paged read carried a total order (the stable-paging fix).
    assert store.range_without_order is False
    assert store.ordered_by == ["everhour_record_id"]
