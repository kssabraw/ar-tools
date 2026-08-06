"""The signed-order drain — what authorizes a UI-triggered spend, and what one tick may do.

DECISIONS.md 2026-08-06. The properties tested here are the gate's properties, not the plumbing's:
at most one order per tick, a claim that cannot be won twice, a budget check that runs before any
money, terminal failure (no machine retry), and an order that always RESOLVES — because a row
stuck `running` blocks its (submarket, keyword) pair forever through the one-active index.

`submit_scan` is stubbed throughout: its orderings have their own tests in `test_scan_runner.py`,
and what matters here is what the drain does around it.
"""

import asyncio

from api.services import scan_queue
from api.services.scan_runner import SubmitReport


# --- a fake that supports the drain's exact query shapes -------------------------------------


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
            self.db.log.append(("update", self.name, dict(self.payload)))
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
        self.log = []

    def table(self, name):
        return _Query(self, name)


class _Settings:
    dataforseo_cost_per_request_cents = 1
    max_market_run_cost_cents = 5000


def _seed(db, *, orders=()):
    db.tables["submarket"] = [{
        "id": "sub-1", "name": "Van Nuys", "market_id": "market-1",
        "center_lat": 34.19, "center_lng": -118.45,
        # radius 5 / spacing 5 → a 5-point grid, same generator as the real 81.
        "grid_radius_miles": 5.0, "grid_spacing_miles": 5.0,
    }]
    db.tables["keyword"] = [{"id": "kw-1", "term": "plumber"}]
    db.tables["scan_request"] = [dict(o) for o in orders]


def _order(id="req-1", created="2026-08-06T01:00:00+00:00", status="pending", **kw):
    return dict(
        {"id": id, "submarket_id": "sub-1", "keyword_id": "kw-1",
         "requested_by": "profile-1", "status": status, "created_at": created},
        **kw,
    )


def _stub_submit(monkeypatch, report=None, exc=None):
    calls = []

    async def submit(db, settings, submarket, keyword):
        calls.append((submarket["id"], keyword["id"]))
        if exc:
            raise exc
        return report

    monkeypatch.setattr(scan_queue.scan_runner, "submit_scan", submit)
    return calls


# --- pure pieces ------------------------------------------------------------------------------


def test_the_estimate_is_one_queued_post_per_point():
    assert scan_queue.estimate_cost_cents(81, 1) == 81
    assert scan_queue.estimate_cost_cents(0, 1) == 0
    assert scan_queue.estimate_cost_cents(-5, 1) == 0


def test_the_budget_denial_names_both_numbers():
    denial = scan_queue.budget_denial(6000, 5000)
    assert denial is not None and "6000" in denial and "5000" in denial
    assert scan_queue.budget_denial(5000, 5000) is None


# --- claiming ---------------------------------------------------------------------------------


def test_an_empty_queue_claims_nothing():
    db = _FakeDB()
    _seed(db)
    assert scan_queue.claim_next_order(db) is None


def test_the_oldest_pending_order_is_claimed_first():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-newer", created="2026-08-06T02:00:00+00:00"),
        _order(id="req-older", created="2026-08-06T01:00:00+00:00"),
    ])
    claimed = scan_queue.claim_next_order(db)
    assert claimed["id"] == "req-older"
    stored = {r["id"]: r["status"] for r in db.tables["scan_request"]}
    assert stored == {"req-older": "running", "req-newer": "pending"}


def test_a_lost_race_claims_nothing_rather_than_double_claiming():
    """The conditional claim: if the row's status moved between the read and the write, the
    update matches nothing and this tick drains NOTHING. Losing a race costs a tick; winning it
    twice costs a paid scan."""
    db = _FakeDB()
    _seed(db, orders=[_order()])

    real_execute = _Query.execute

    def racing_execute(self):
        # Somebody else claims the row between our select and our update.
        if self.op == "update" and self.name == "scan_request":
            for row in self.db.tables["scan_request"]:
                if row["status"] == "pending":
                    row["status"] = "running"
        return real_execute(self)

    _Query.execute = racing_execute
    try:
        assert scan_queue.claim_next_order(db) is None
    finally:
        _Query.execute = real_execute


def test_terminal_orders_are_never_claimed():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-done", status="done"),
        _order(id="req-failed", status="failed"),
        _order(id="req-cancelled", status="cancelled"),
    ])
    assert scan_queue.claim_next_order(db) is None


# --- the drain --------------------------------------------------------------------------------


def test_an_idle_tick_reports_idle_and_touches_nothing(monkeypatch):
    db = _FakeDB()
    _seed(db)
    calls = _stub_submit(monkeypatch, report=SubmitReport())

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and report.outcome == "idle"
    assert calls == []


def test_a_successful_order_resolves_done_with_its_snapshot(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_submit(
        monkeypatch, report=SubmitReport(snapshot_id="snap-1", posted=5, expected_points=5)
    )

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert calls == [("sub-1", "kw-1")]
    assert report.outcome == "done" and report.snapshot_id == "snap-1" and report.posted == 5
    row = db.tables["scan_request"][0]
    assert row["status"] == "done"
    assert row["snapshot_id"] == "snap-1"
    assert row["finished_at"]


def test_only_one_order_runs_per_tick(monkeypatch):
    """The UI-path descendant of the one-submarket ruling: a queue of N orders takes N ticks."""
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-1", created="2026-08-06T01:00:00+00:00"),
        _order(id="req-2", created="2026-08-06T02:00:00+00:00",
               submarket_id="sub-1", keyword_id="kw-1"),
    ])
    calls = _stub_submit(
        monkeypatch, report=SubmitReport(snapshot_id="snap-1", posted=5, expected_points=5)
    )

    asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert len(calls) == 1
    statuses = sorted(r["status"] for r in db.tables["scan_request"])
    assert statuses == ["done", "pending"]


def test_the_budget_gate_runs_before_any_money(monkeypatch):
    tight = _Settings()
    tight.max_market_run_cost_cents = 3  # 5-point grid at 1¢ = 5¢ > 3¢
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_submit(monkeypatch, report=SubmitReport())

    report = asyncio.run(scan_queue.drain_one(db, tight))

    assert calls == [], "submit_scan must not be reached past a budget refusal"
    assert report.outcome == "failed" and "max_market_run_cost_cents" in report.error
    row = db.tables["scan_request"][0]
    assert row["status"] == "failed" and "refused before anything was posted" in row["error"]


def test_a_vanished_target_fails_the_order_instead_of_sticking_it_running(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(submarket_id="sub-gone")])
    calls = _stub_submit(monkeypatch, report=SubmitReport())

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert calls == []
    assert report.outcome == "failed"
    assert db.tables["scan_request"][0]["status"] == "failed"


def test_a_submit_crash_resolves_the_order_and_does_not_propagate(monkeypatch):
    """A raise past the drain leaves the order stuck `running`, which blocks its pair forever
    through the one-active index. The order must resolve from whatever actually happened."""
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_submit(monkeypatch, exc=RuntimeError("provider melted"))

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and "provider melted" in report.error
    row = db.tables["scan_request"][0]
    assert row["status"] == "failed" and "provider melted" in row["error"]


def test_a_zero_post_order_fails_but_keeps_its_snapshot_findable(monkeypatch):
    """cmd_scan's reasoning, applied to the queue: posting nothing while believing a scan
    happened is the worst outcome available. And the snapshot id STAYS on the failed order —
    the paid-task bookkeeping hangs off it, so orphaning it hides whatever was spent."""
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_submit(
        monkeypatch, report=SubmitReport(snapshot_id="snap-1", posted=0, expected_points=5)
    )

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed"
    row = db.tables["scan_request"][0]
    assert row["status"] == "failed"
    assert row["snapshot_id"] == "snap-1"


def test_a_failed_order_is_terminal_not_retried(monkeypatch):
    """The machine never re-runs a failed order — a human re-places it having read the error.
    Automatic retry is one click becoming N paid scans (§6.4 in miniature)."""
    db = _FakeDB()
    _seed(db, orders=[_order(status="failed", error="budget")])
    calls = _stub_submit(monkeypatch, report=SubmitReport())

    report = asyncio.run(scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and calls == []


# --- command wiring ---------------------------------------------------------------------------


def test_tick_is_not_spend_gated_and_is_wired():
    """`tick` spends only on a signed order, which IS its confirmation (DECISIONS.md
    2026-08-06). Listing it in PAID_COMMANDS would make every cron heartbeat refuse — the §8a
    collect-gating mistake respelled. If this test starts failing, read that decision before
    'fixing' the gate."""
    from api.scripts.run_market import PAID_COMMANDS, cmd_tick  # noqa: F401

    assert "tick" not in PAID_COMMANDS
    assert "collect" not in PAID_COMMANDS  # unchanged by the tick build; §8a's own test also pins this
