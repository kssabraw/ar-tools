"""The onboard-order drain — discover → filter → scan on one signed order.

Sibling to `test_scan_queue`. The claim/budget properties are the same gate's, so they are checked
the same way; what is NEW here is the STAGED multi-step run: which stage a failure stops at, that a
budget or ingest-cost refusal spends nothing, that an ingest/filter failure never reaches the scan,
and that a scan failure still resolves the order with its snapshot findable.

`run_ingest`, `run_filter`, and `submit_scan` are stubbed — their own orderings have their own
tests; what matters here is what the drain does around them.
"""

import asyncio
from types import SimpleNamespace

from api.services import onboard_queue
from api.services.scan_runner import SubmitReport


# --- a fake that supports the drain's query shapes (mirrors test_scan_queue) -------------------


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
    db.tables["market"] = [{"id": "market-1", "name": "Van Nuys", "region": "CA, USA"}]
    db.tables["submarket"] = [{
        "id": "sub-1", "name": "Lake Balboa", "market_id": "market-1",
        "center_lat": 34.19, "center_lng": -118.45,
        # radius 5 / spacing 5 → a 5-point grid, same generator as the real 81.
        "grid_radius_miles": 5.0, "grid_spacing_miles": 5.0,
    }]
    db.tables["keyword"] = [{"id": "kw-1", "term": "plumber"}]
    db.tables["onboard_request"] = [dict(o) for o in orders]


def _order(id="ob-1", created="2026-08-08T01:00:00+00:00", status="pending", **kw):
    return dict(
        {"id": id, "submarket_id": "sub-1", "keyword_id": "kw-1", "category": "plumber",
         "region": "CA, USA", "requested_by": "profile-1", "status": status, "created_at": created},
        **kw,
    )


def _stub_pipeline(monkeypatch, *, ingest=5, survived=3, submit=None, ingest_exc=None,
                   filter_exc=None, submit_exc=None):
    """Stub the three pipeline stages; return a dict of call-recorders."""
    calls = {"ingest": [], "filter": [], "submit": []}

    async def _run_ingest(**kw):
        calls["ingest"].append(kw)
        if ingest_exc:
            raise ingest_exc
        return SimpleNamespace(prospects_written=ingest)

    def _run_filter(**kw):
        calls["filter"].append(kw)
        if filter_exc:
            raise filter_exc
        return SimpleNamespace(survived=survived)

    async def _submit(db, settings, submarket, keyword):
        calls["submit"].append((submarket["id"], keyword["id"]))
        if submit_exc:
            raise submit_exc
        return submit if submit is not None else SubmitReport()

    monkeypatch.setattr(onboard_queue, "run_ingest", _run_ingest)
    monkeypatch.setattr(onboard_queue, "run_filter", _run_filter)
    monkeypatch.setattr(onboard_queue.scan_runner, "submit_scan", _submit)
    monkeypatch.setattr(onboard_queue.seeding, "submarket_rows_to_tiling", lambda rows: rows)
    return calls


# --- claiming (the gate's properties, same as scan_queue) -------------------------------------


def test_empty_queue_claims_nothing():
    db = _FakeDB()
    _seed(db)
    assert onboard_queue.claim_next_order(db) is None


def test_oldest_pending_claimed_first():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="ob-new", created="2026-08-08T02:00:00+00:00"),
        _order(id="ob-old", created="2026-08-08T01:00:00+00:00"),
    ])
    claimed = onboard_queue.claim_next_order(db)
    assert claimed["id"] == "ob-old"
    stored = {r["id"]: r["status"] for r in db.tables["onboard_request"]}
    assert stored == {"ob-old": "running", "ob-new": "pending"}


def test_terminal_orders_never_claimed():
    db = _FakeDB()
    _seed(db, orders=[
        _order(id="ob-done", status="done"),
        _order(id="ob-failed", status="failed"),
        _order(id="ob-cancelled", status="cancelled"),
    ])
    assert onboard_queue.claim_next_order(db) is None


# --- the happy path: all three stages run -----------------------------------------------------


def test_successful_order_runs_all_stages_and_records_counts(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_pipeline(
        monkeypatch, ingest=7, survived=4,
        submit=SubmitReport(snapshot_id="snap-1", posted=5, expected_points=5),
    )

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert [c["categories"] for c in calls["ingest"]] == [["plumber"]]
    assert calls["ingest"][0]["region"] == "CA, USA"
    assert calls["submit"] == [("sub-1", "kw-1")]
    assert report.outcome == "done" and report.stage == "done"
    assert report.prospects_ingested == 7 and report.prospects_survived == 4
    assert report.snapshot_id == "snap-1" and report.posted == 5
    row = db.tables["onboard_request"][0]
    assert row["status"] == "done" and row["snapshot_id"] == "snap-1"
    assert row["prospects_ingested"] == 7 and row["prospects_survived"] == 4
    assert row["finished_at"]


def test_idle_tick_touches_nothing(monkeypatch):
    db = _FakeDB()
    _seed(db)
    calls = _stub_pipeline(monkeypatch)
    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))
    assert report.claimed == 0 and report.outcome == "idle"
    assert calls["ingest"] == [] and calls["submit"] == []


# --- staged failure ---------------------------------------------------------------------------


def test_budget_refusal_spends_nothing(monkeypatch):
    tight = _Settings()
    tight.max_market_run_cost_cents = 3  # 5-point grid at 1¢ = 5¢ > 3¢
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_pipeline(monkeypatch)

    report = asyncio.run(onboard_queue.drain_one(db, tight))

    assert calls["ingest"] == [] and calls["submit"] == [], "no stage runs past a budget refusal"
    assert report.outcome == "failed" and "max_market_run_cost_cents" in report.error
    assert db.tables["onboard_request"][0]["status"] == "failed"


def test_ingest_cost_refusal_fails_before_scan(monkeypatch):
    from api.services.cost import CostLimitExceeded

    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_pipeline(monkeypatch, ingest_exc=CostLimitExceeded(900, 500))

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert calls["submit"] == [], "the scan must not run when discovery was refused"
    assert report.outcome == "failed" and report.stage == "ingest"
    assert "refused before spending" in report.error


def test_ingest_error_fails_without_scanning(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_pipeline(monkeypatch, ingest_exc=RuntimeError("outscraper melted"))

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert calls["submit"] == []
    assert report.outcome == "failed" and report.stage == "ingest"
    assert "outscraper melted" in report.error
    assert db.tables["onboard_request"][0]["status"] == "failed"


def test_filter_error_fails_after_ingest_before_scan(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    calls = _stub_pipeline(monkeypatch, ingest=6, filter_exc=RuntimeError("bad rule"))

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert calls["ingest"] and calls["submit"] == []
    assert report.outcome == "failed" and report.stage == "filter"
    assert report.prospects_ingested == 6  # discovery spend is recorded even though the scan never ran
    assert "bad rule" in report.error


def test_scan_crash_resolves_the_order(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_pipeline(monkeypatch, submit_exc=RuntimeError("provider melted"))

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed" and report.stage == "scan"
    assert "provider melted" in report.error
    assert db.tables["onboard_request"][0]["status"] == "failed"


def test_zero_post_fails_but_keeps_snapshot_findable(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order()])
    _stub_pipeline(
        monkeypatch, submit=SubmitReport(snapshot_id="snap-1", posted=0, expected_points=5)
    )

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert report.outcome == "failed"
    row = db.tables["onboard_request"][0]
    assert row["status"] == "failed" and row["snapshot_id"] == "snap-1"


def test_vanished_target_fails_instead_of_sticking_running(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(submarket_id="sub-gone")])
    calls = _stub_pipeline(monkeypatch)

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert calls["ingest"] == [] and calls["submit"] == []
    assert report.outcome == "failed"
    assert db.tables["onboard_request"][0]["status"] == "failed"


def test_failed_order_is_terminal_not_retried(monkeypatch):
    db = _FakeDB()
    _seed(db, orders=[_order(status="failed", error="budget")])
    calls = _stub_pipeline(monkeypatch)

    report = asyncio.run(onboard_queue.drain_one(db, _Settings()))

    assert report.claimed == 0 and calls["ingest"] == []
