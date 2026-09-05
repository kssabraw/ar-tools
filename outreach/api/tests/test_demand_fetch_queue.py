"""The demand signed-order drain — the valuation's search-volume fetch, auto-run on scan finalize.

Sibling of `test_organic_scan_queue.py`; the same gate properties are pinned (one order per tick, a
claim that cannot be won twice, budget-before-money, terminal failure, an order that always RESOLVES
so a stuck `running` row can't block its snapshot×keyword pair) plus the demand-specific facts: a
fresh cache drains as a free `done` no-op, and auto-enqueue skips a snapshot whose (keyword,
location_token) is already cached fresh.

`demand_fetch.fetch_demand` is stubbed throughout — its own behaviour is tested in test_demand_fetch.
"""

import asyncio
from datetime import datetime, timezone

from api.services import demand_fetch_queue
from api.services.demand_fetch import DemandFetchReport


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.filters = []
        self._order = None
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        return _Query(self.db, self.name, "insert", payload)

    def update(self, payload):
        return _Query(self.db, self.name, "update", payload)

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        return all(str(row.get(c)) == str(v) for c, v in self.filters)

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = [dict(r) for r in payload]
            for i, row in enumerate(written):
                row.setdefault("id", f"{self.name}-{len(rows) + i}")
            rows.extend(written)
            return _Result(written)
        if self.op == "update":
            hit = [r for r in rows if self._matches(r)]
            for row in hit:
                row.update(self.payload)
            return _Result([dict(r) for r in hit])
        found = [r for r in rows if self._matches(r)]
        if self._order:
            column, desc = self._order
            found = sorted(found, key=lambda r: str(r.get(column) or ""), reverse=desc)
        if self._limit is not None:
            found = found[: self._limit]
        return _Result([dict(r) for r in found])


class _FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self, name)


class _Settings:
    dataforseo_cost_per_request_cents = 1
    max_market_run_cost_cents = 5000
    demand_auto_enabled = True
    demand_auto_actor_id = "00000000-0000-0000-0000-000000000000"
    demand_refresh_days = 30


def _seed(db, *, orders=(), keyword_demand=(), submarket=None):
    db.tables["scan_snapshot"] = [{"id": "snap-1", "submarket_id": "sub-1", "keyword_id": "kw-1"}]
    db.tables["keyword"] = [{"id": "kw-1", "term": "plumber"}]
    db.tables["submarket"] = [submarket or {"id": "sub-1", "market_id": "market-1"}]
    db.tables["keyword_demand"] = [dict(r) for r in keyword_demand]
    db.tables["demand_fetch_request"] = [dict(o) for o in orders]


def _order(id="req-1", created="2026-09-05T01:00:00+00:00", status="pending", **kw):
    return dict(
        {"id": id, "snapshot_id": "snap-1", "keyword_id": "kw-1",
         "requested_by": "profile-1", "status": status, "created_at": created},
        **kw,
    )


def _stub_fetch(monkeypatch, report=None, exc=None):
    calls = []

    async def fetch(db, settings, snapshot, keyword_term, *, market_id, client=None):
        calls.append((snapshot["id"], keyword_term, market_id))
        if exc:
            raise exc
        return report

    monkeypatch.setattr(demand_fetch_queue.demand_fetch, "fetch_demand", fetch)
    return calls


# --- pure -------------------------------------------------------------------------------------


def test_estimate_and_budget_denial():
    assert demand_fetch_queue.estimate_cost_cents(1) == 1
    assert demand_fetch_queue.estimate_cost_cents(-5) == 0
    denial = demand_fetch_queue.budget_denial(6000, 5000)
    assert denial and "6000" in denial and "5000" in denial
    assert demand_fetch_queue.budget_denial(1, 5000) is None


# --- claiming ---------------------------------------------------------------------------------


def test_oldest_pending_claimed_terminal_never():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="newer", created="2026-09-05T02:00:00+00:00"),
        _order(id="older", created="2026-09-05T01:00:00+00:00"),
        _order(id="done", status="done"),
    ])
    claimed = demand_fetch_queue.claim_next_order(db)
    assert claimed["id"] == "older"
    stored = {r["id"]: r["status"] for r in db.tables["demand_fetch_request"]}
    assert stored["older"] == "running" and stored["newer"] == "pending" and stored["done"] == "done"


# --- the drain --------------------------------------------------------------------------------


def test_idle_tick_touches_nothing(monkeypatch):
    db = _FakeDB()
    _seed(db)
    calls = _stub_fetch(monkeypatch, report=DemandFetchReport(stored=True))
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert report.claimed == 0 and report.outcome == "idle" and calls == []


def test_successful_order_resolves_done_with_right_target(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_fetch(
        monkeypatch,
        report=DemandFetchReport(stored=True, location_token="Los Angeles", search_volume=1200),
    )
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert calls == [("snap-1", "plumber", "market-1")]
    assert report.outcome == "done" and report.search_volume == 1200
    assert db.tables["demand_fetch_request"][0]["status"] == "done"


def test_fresh_cache_is_a_free_done(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_fetch(monkeypatch, report=DemandFetchReport(already_cached=True, stored=False))
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert report.outcome == "done" and report.already_cached is True
    assert db.tables["demand_fetch_request"][0]["status"] == "done"


def test_stored_nothing_fails_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_fetch(monkeypatch, report=DemandFetchReport(stored=False, problems=["no location"]))
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert report.outcome == "failed" and "no location" in report.error
    assert db.tables["demand_fetch_request"][0]["status"] == "failed"


def test_budget_gate_runs_before_money(monkeypatch):
    tight = _Settings()
    tight.max_market_run_cost_cents = 0
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_fetch(monkeypatch, report=DemandFetchReport(stored=True))
    report = asyncio.run(demand_fetch_queue.drain_one(db, tight))
    assert calls == [] and report.outcome == "failed" and "max_market_run_cost_cents" in report.error


def test_vanished_snapshot_fails(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(snapshot_id="gone")])
    calls = _stub_fetch(monkeypatch, report=DemandFetchReport(stored=True))
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert calls == [] and report.outcome == "failed"
    assert db.tables["demand_fetch_request"][0]["status"] == "failed"


def test_fetch_crash_resolves_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_fetch(monkeypatch, exc=RuntimeError("provider melted"))
    report = asyncio.run(demand_fetch_queue.drain_one(db, _Settings()))
    assert report.outcome == "failed" and "provider melted" in report.error
    assert db.tables["demand_fetch_request"][0]["status"] == "failed"


# --- auto-enqueue -----------------------------------------------------------------------------


def test_auto_enqueue_places_one_order():
    db = _FakeDB()
    _seed(db)
    assert demand_fetch_queue.enqueue_for_snapshot(db, _Settings(), "snap-1") is True
    orders = db.tables["demand_fetch_request"]
    assert len(orders) == 1
    assert orders[0]["requested_by"] == "00000000-0000-0000-0000-000000000000"
    assert orders[0]["note"] == demand_fetch_queue._AUTO_NOTE


def test_auto_enqueue_idempotent_on_prior_order():
    db = _FakeDB()
    _seed(db, orders=[_order(id="prior", status="done")])
    assert demand_fetch_queue.enqueue_for_snapshot(db, _Settings(), "snap-1") is False
    assert len(db.tables["demand_fetch_request"]) == 1


def test_auto_enqueue_skips_when_cache_is_fresh():
    """Guard 2: a fresh keyword_demand row for this snapshot's (keyword, submarket token) means
    there is nothing to fetch — don't even enqueue a no-op order."""
    db = _FakeDB()
    fresh = datetime.now(timezone.utc).isoformat()
    _seed(
        db,
        submarket={"id": "sub-1", "market_id": "market-1", "location_token": "Los Angeles"},
        keyword_demand=[{"keyword": "plumber", "location_token": "Los Angeles", "fetched_at": fresh}],
    )
    assert demand_fetch_queue.enqueue_for_snapshot(db, _Settings(), "snap-1") is False
    assert db.tables["demand_fetch_request"] == []


def test_auto_enqueue_places_order_when_cache_is_stale():
    db = _FakeDB()
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    _seed(
        db,
        submarket={"id": "sub-1", "market_id": "market-1", "location_token": "Los Angeles"},
        keyword_demand=[{"keyword": "plumber", "location_token": "Los Angeles", "fetched_at": stale}],
    )
    assert demand_fetch_queue.enqueue_for_snapshot(db, _Settings(), "snap-1") is True
    assert len(db.tables["demand_fetch_request"]) == 1


def test_auto_enqueue_disabled_is_a_noop():
    settings = _Settings()
    settings.demand_auto_enabled = False
    db = _FakeDB()
    _seed(db)
    assert demand_fetch_queue.enqueue_for_snapshot(db, settings, "snap-1") is False
    assert db.tables["demand_fetch_request"] == []
