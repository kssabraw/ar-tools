"""The organic signed-order drain — the report's ORGANIC signal, run from a UI click.

Sibling of `test_scan_queue.py`; the same gate properties are pinned here (one order per tick, a
claim that cannot be won twice, budget-before-money, terminal failure, an order that always
RESOLVES so a stuck `running` row can't block its snapshot×keyword pair through the one-active
index) plus the two organic-specific facts: an already-captured snapshot drains as a free `done`
no-op, and the exact snapshot + keyword the report reads are what the capture is handed.

`organic_scan.capture_organic` is stubbed throughout — its own behaviour is tested elsewhere; what
matters here is what the drain does around it (and that it is never reached past a refusal).
"""

import asyncio

from api.services import organic_scan_queue
from api.services.organic_scan import OrganicCaptureReport


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


def _seed(db, *, orders=()):
    db.tables["scan_snapshot"] = [{
        "id": "snap-1", "submarket_id": "sub-1", "center_lat": 34.19, "center_lng": -118.45,
        "scanned_at": "2026-08-10T00:00:00+00:00", "keyword_id": "kw-1",
    }]
    db.tables["keyword"] = [{"id": "kw-1", "term": "plumber"}]
    db.tables["submarket"] = [{"id": "sub-1", "market_id": "market-1"}]
    db.tables["organic_scan_request"] = [dict(o) for o in orders]


def _order(id="req-1", created="2026-08-10T01:00:00+00:00", status="pending", **kw):
    return dict(
        {"id": id, "snapshot_id": "snap-1", "keyword_id": "kw-1",
         "requested_by": "profile-1", "status": status, "created_at": created},
        **kw,
    )


def _stub_capture(monkeypatch, report=None, exc=None):
    calls = []

    async def capture(db, settings, snapshot, keyword_term, *, market_id, client=None):
        calls.append((snapshot["id"], keyword_term, market_id))
        if exc:
            raise exc
        return report

    monkeypatch.setattr(organic_scan_queue.organic_scan, "capture_organic", capture)
    return calls


# --- pure pieces ------------------------------------------------------------------------------


def test_the_estimate_is_one_request():
    assert organic_scan_queue.estimate_cost_cents(1) == 1
    assert organic_scan_queue.estimate_cost_cents(-5) == 0


def test_the_budget_denial_names_both_numbers():
    denial = organic_scan_queue.budget_denial(6000, 5000)
    assert denial is not None and "6000" in denial and "5000" in denial
    assert organic_scan_queue.budget_denial(1, 5000) is None


# --- claiming ---------------------------------------------------------------------------------


def test_an_empty_queue_claims_nothing():
    db = _FakeDB()
    _seed(db)
    assert organic_scan_queue.claim_next_order(db) is None


def test_the_oldest_pending_order_is_claimed_first():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-newer", created="2026-08-10T02:00:00+00:00"),
        _order(id="req-older", created="2026-08-10T01:00:00+00:00"),
    ])
    claimed = organic_scan_queue.claim_next_order(db)
    assert claimed["id"] == "req-older"
    stored = {r["id"]: r["status"] for r in db.tables["organic_scan_request"]}
    assert stored == {"req-older": "running", "req-newer": "pending"}


def test_terminal_orders_are_never_claimed():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-done", status="done"),
        _order(id="req-failed", status="failed"),
        _order(id="req-cancelled", status="cancelled"),
    ])
    assert organic_scan_queue.claim_next_order(db) is None


# --- the drain --------------------------------------------------------------------------------


def test_an_idle_tick_reports_idle_and_touches_nothing(monkeypatch):
    db = _FakeDB()
    _seed(db)
    calls = _stub_capture(monkeypatch, report=OrganicCaptureReport(stored=True))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and report.outcome == "idle"
    assert calls == []


def test_a_successful_order_resolves_done_and_hands_the_right_target(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_capture(
        monkeypatch, report=OrganicCaptureReport(snapshot_id="snap-1", keyword="plumber", stored=True)
    )

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    # The capture is handed the exact snapshot + keyword the report reads, and the resolved market.
    assert calls == [("snap-1", "plumber", "market-1")]
    assert report.outcome == "done"
    row = db.tables["organic_scan_request"][0]
    assert row["status"] == "done" and row["finished_at"]


def test_an_already_captured_snapshot_is_a_free_done(monkeypatch):
    """capture_organic is idempotent per snapshot — a re-order (or a second prospect in the same
    submarket) drains `done` without re-billing, never `failed`."""
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_capture(monkeypatch, report=OrganicCaptureReport(already_captured=True, stored=False))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "done" and report.already_captured is True
    assert db.tables["organic_scan_request"][0]["status"] == "done"


def test_a_capture_that_stores_nothing_fails_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_capture(
        monkeypatch, report=OrganicCaptureReport(stored=False, problems=["provider 500"])
    )

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and "provider 500" in report.error
    assert db.tables["organic_scan_request"][0]["status"] == "failed"


def test_the_budget_gate_runs_before_any_money(monkeypatch):
    tight = _Settings()
    tight.max_market_run_cost_cents = 0  # 1¢ organic request > 0¢
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_capture(monkeypatch, report=OrganicCaptureReport(stored=True))

    report = asyncio.run(organic_scan_queue.drain_one(db, tight))

    assert calls == [], "capture must not be reached past a budget refusal"
    assert report.outcome == "failed" and "max_market_run_cost_cents" in report.error


def test_a_vanished_snapshot_fails_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(snapshot_id="snap-gone")])
    calls = _stub_capture(monkeypatch, report=OrganicCaptureReport(stored=True))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert calls == []
    assert report.outcome == "failed"
    assert db.tables["organic_scan_request"][0]["status"] == "failed"


def test_a_snapshot_without_a_centre_fails_before_billing(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    db.tables["scan_snapshot"][0]["center_lat"] = None
    calls = _stub_capture(monkeypatch, report=OrganicCaptureReport(stored=True))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert calls == [] and report.outcome == "failed" and "centre" in report.error


def test_a_capture_crash_resolves_the_order_and_does_not_propagate(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_capture(monkeypatch, exc=RuntimeError("provider melted"))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and "provider melted" in report.error
    assert db.tables["organic_scan_request"][0]["status"] == "failed"


def test_a_failed_order_is_terminal_not_retried(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(status="failed", error="budget")])
    calls = _stub_capture(monkeypatch, report=OrganicCaptureReport(stored=True))

    report = asyncio.run(organic_scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and calls == []
