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

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def execute(self):
        if self._mode == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            self._store.inserts.setdefault(self._table, []).extend(rows)
            return type("R", (), {"data": rows})()
        if self._mode == "update":
            self._store.updates.setdefault(self._table, []).append(self._payload)
            return type("R", (), {"data": []})()
        return type("R", (), {"data": list(self._store.reads.get(self._table, []))})()


class _Store:
    def __init__(self, reads=None):
        self.reads = reads or {}
        self.inserts: dict[str, list] = {}
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
