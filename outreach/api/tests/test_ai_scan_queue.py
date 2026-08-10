"""The AI-visibility signed-order drain — the report's AI signal, run from a UI click.

Sibling of `test_scan_queue.py` / `test_organic_scan_queue.py`; the same gate properties are pinned
here, plus the AI-specific distinction that governs how an order resolves: `run_ai_scan` is
best-effort PER ENGINE (a failed engine is stored `present=False`, not raised), so the order is
`done` when at least one engine stored a row and `failed` (with the per-engine problems) only when
NOTHING stored — because a total store-failure is an outage, and recording it as success would let
"we couldn't reach the AI" read as "the AI doesn't know this business", the strongest false pitch.

`ai_visibility.run_ai_scan` is stubbed throughout.
"""

import asyncio

from api.services import ai_scan_queue
from api.services.ai_visibility import AiScanReport


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
    ai_visibility_openai_cost_cents = 2
    max_market_run_cost_cents = 5000


def _seed(db, *, orders=()):
    db.tables["ai_region"] = [
        {"id": "reg-1", "name": "Long Beach", "name_level": "city", "market_id": "market-1"}
    ]
    db.tables["keyword"] = [{"id": "kw-1", "term": "plumber"}]
    db.tables["ai_scan_request"] = [dict(o) for o in orders]


def _order(id="req-1", created="2026-08-10T01:00:00+00:00", status="pending", **kw):
    return dict(
        {"id": id, "ai_region_id": "reg-1", "keyword_id": "kw-1",
         "requested_by": "profile-1", "status": status, "created_at": created},
        **kw,
    )


def _stub_scan(monkeypatch, report=None, exc=None):
    calls = []

    async def run(db, settings, ai_region, keyword, *, engines=None, market_id=None):
        calls.append((ai_region["id"], keyword["id"], market_id))
        if exc:
            raise exc
        return report

    monkeypatch.setattr(ai_scan_queue.ai_visibility, "run_ai_scan", run)
    return calls


# --- pure pieces ------------------------------------------------------------------------------


def test_the_estimate_is_openai_plus_one_aio_request():
    assert ai_scan_queue.estimate_cost_cents(2, 1) == 3
    assert ai_scan_queue.estimate_cost_cents(-2, -1) == 0


def test_the_budget_denial_names_both_numbers():
    denial = ai_scan_queue.budget_denial(6000, 5000)
    assert denial is not None and "6000" in denial and "5000" in denial
    assert ai_scan_queue.budget_denial(3, 5000) is None


# --- claiming ---------------------------------------------------------------------------------


def test_the_oldest_pending_order_is_claimed_first():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="req-newer", created="2026-08-10T02:00:00+00:00"),
        _order(id="req-older", created="2026-08-10T01:00:00+00:00"),
    ])
    claimed = ai_scan_queue.claim_next_order(db)
    assert claimed["id"] == "req-older"
    stored = {r["id"]: r["status"] for r in db.tables["ai_scan_request"]}
    assert stored == {"req-older": "running", "req-newer": "pending"}


def test_terminal_orders_are_never_claimed():
    db = _FakeDB()
    _seed(db, orders=[_order(id="d", status="done"), _order(id="f", status="failed")])
    assert ai_scan_queue.claim_next_order(db) is None


# --- the drain --------------------------------------------------------------------------------


def test_an_idle_tick_reports_idle_and_touches_nothing(monkeypatch):
    db = _FakeDB()
    _seed(db)
    calls = _stub_scan(monkeypatch, report=AiScanReport(stored=2))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and report.outcome == "idle" and calls == []


def test_a_stored_scan_resolves_done_and_hands_the_right_target(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_scan(monkeypatch, report=AiScanReport(ai_region="Long Beach", keyword="plumber", stored=2))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert calls == [("reg-1", "kw-1", "market-1")]
    assert report.outcome == "done" and report.stored == 2
    assert db.tables["ai_scan_request"][0]["status"] == "done"


def test_a_scan_that_stores_nothing_fails_rather_than_manufacturing_invisibility(monkeypatch):
    """stored == 0 is an outage (every engine failed to store), NOT 'the AI doesn't know you'. The
    order fails with the per-engine problems so a human re-places it, never records a false miss."""
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_scan(monkeypatch, report=AiScanReport(stored=0, problems=["chatgpt skipped — missing OPENAI_API_KEY"]))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and "OPENAI_API_KEY" in report.error
    assert db.tables["ai_scan_request"][0]["status"] == "failed"


def test_the_budget_gate_runs_before_any_money(monkeypatch):
    tight = _Settings()
    tight.max_market_run_cost_cents = 1  # 2¢ + 1¢ = 3¢ > 1¢
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_scan(monkeypatch, report=AiScanReport(stored=2))

    report = asyncio.run(ai_scan_queue.drain_one(db, tight))

    assert calls == [], "run_ai_scan must not be reached past a budget refusal"
    assert report.outcome == "failed" and "max_market_run_cost_cents" in report.error


def test_a_vanished_region_fails_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(ai_region_id="reg-gone")])
    calls = _stub_scan(monkeypatch, report=AiScanReport(stored=2))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert calls == [] and report.outcome == "failed"
    assert db.tables["ai_scan_request"][0]["status"] == "failed"


def test_a_scan_crash_resolves_the_order_and_does_not_propagate(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_scan(monkeypatch, exc=RuntimeError("openai melted"))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and "openai melted" in report.error
    assert db.tables["ai_scan_request"][0]["status"] == "failed"


def test_a_failed_order_is_terminal_not_retried(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(status="failed", error="budget")])
    calls = _stub_scan(monkeypatch, report=AiScanReport(stored=2))

    report = asyncio.run(ai_scan_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and calls == []
