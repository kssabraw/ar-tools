"""The name-scrape drain — the FREE analogue of the enrich drain. What's tested is what MATTERS:

idempotent skip (found/no_names never re-scraped; unreachable IS retried), replace-on-place scoped
to `site_scrape` so Outscraper contacts survive, the per-order ceiling, per-prospect failure
isolation, and the measured-vs-found status. `name_scrape.scrape_names` is stubbed — its fetch
behaviour is `test_name_scrape`'s subject, not this."""

import asyncio

from api.services import name_scrape, name_scrape_queue
from api.services.name_extract import ExtractedName


# --- a fake supporting the drain's query shapes (in_/not_.is_/delete/upsert/range) -------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Not:
    def __init__(self, q):
        self._q = q

    def is_(self, column, _value):
        return self._q


class _Query:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.eqs = []
        self.in_filters = []
        self._order = None
        self._limit = None
        self._range = None
        self._conflict = None
        self.not_ = _Not(self)

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        return _Query(self.db, self.name, "insert", payload)

    def update(self, payload):
        return _Query(self.db, self.name, "update", payload)

    def delete(self):
        return _Query(self.db, self.name, "delete")

    def upsert(self, payload, on_conflict=None):
        q = _Query(self.db, self.name, "upsert", payload)
        q._conflict = on_conflict
        return q

    def eq(self, column, value):
        self.eqs.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filters.append((column, list(values)))
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def _matches(self, row):
        if not all(str(row.get(c)) == str(v) for c, v in self.eqs):
            return False
        return all(row.get(c) in vs for c, vs in self.in_filters)

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = [dict(r) for r in payload]
            for i, row in enumerate(written):
                row.setdefault("id", f"{self.name}-{len(rows) + i}")
            rows.extend(written)
            return _Result(written)
        if self.op == "upsert":
            key = self._conflict
            new = dict(self.payload)
            hit = next((r for r in rows if r.get(key) == new.get(key)), None)
            if hit:
                hit.update(new)
                return _Result([dict(hit)])
            new.setdefault("id", f"{self.name}-{len(rows)}")
            rows.append(new)
            return _Result([dict(new)])
        if self.op == "update":
            hit = [r for r in rows if self._matches(r)]
            for row in hit:
                row.update(self.payload)
            return _Result([dict(r) for r in hit])
        if self.op == "delete":
            keep = [r for r in rows if not self._matches(r)]
            self.db.tables[self.name] = keep
            return _Result([{"removed": len(rows) - len(keep)}])
        found = [r for r in rows if self._matches(r)]
        if self._order:
            column, desc = self._order
            found = sorted(found, key=lambda r: str(r.get(column) or ""), reverse=desc)
        if self._range is not None:
            start, end = self._range
            found = found[start : end + 1]
        if self._limit is not None:
            found = found[: self._limit]
        return _Result([dict(r) for r in found])


class _FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self, name)


class _Settings:
    name_scrape_chunk_size = 10
    name_scrape_orders_per_tick = 5
    name_scrape_max_places_per_order = 200
    name_scrape_concurrency = 4


def _seed(db, *, prospects, orders):
    db.tables["prospect"] = [dict(p) for p in prospects]
    db.tables["name_scrape_request"] = [dict(o) for o in orders]
    db.tables.setdefault("prospect_name_scrape", [])
    db.tables.setdefault("prospect_contact", [])


def _order(id="ord-1", prospect_ids=("p1",), status="pending", **kw):
    return dict(
        {
            "id": id,
            "prospect_ids": list(prospect_ids),
            "requested_by": "staff-1",
            "status": status,
            "created_at": "2026-08-20T01:00:00+00:00",
        },
        **kw,
    )


def _result(pid, *, status, names=(), fetch_status="ok", pages=1, urls=("https://x.com",)):
    made = tuple(
        ExtractedName(full_name=n, title="Owner", source_kind="text", evidence=f"{n}, Owner")
        for n in names
    )
    return name_scrape.NameScrapeResult(
        prospect_id=pid, status=status, fetch_status=fetch_status, names=made,
        pages_fetched=pages, source_urls=urls,
    )


def _stub(monkeypatch, by_id, errors=None, raises=None):
    async def scrape_names(settings, prospects, **_k):
        if raises:
            raise raises
        results = [by_id[p["id"]] for p in prospects if p["id"] in by_id]
        return results, list(errors or [])

    monkeypatch.setattr(name_scrape_queue.name_scrape, "scrape_names", scrape_names)


# --- claiming ---------------------------------------------------------------------------------


def test_only_pending_orders_are_claimed():
    db = _FakeDB()
    _seed(db, prospects=[], orders=[_order(status="done")])
    assert name_scrape_queue.claim_next_order(db) is None


# --- the drain --------------------------------------------------------------------------------


def test_a_found_order_stores_site_scrape_contacts_and_a_found_marker(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "name": "Acme", "website": "https://acme.com"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub(monkeypatch, {"p1": _result("p1", status="found", names=["Jane Doe", "Bob Fox"])})

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    o = report.orders[0]
    assert o.outcome == "done" and o.found == 1 and o.names == 2
    contacts = db.tables["prospect_contact"]
    assert len(contacts) == 2 and all(c["source"] == "site_scrape" for c in contacts)
    marker = db.tables["prospect_name_scrape"][0]
    assert marker["status"] == "found" and marker["name_count"] == 2
    assert db.tables["name_scrape_request"][0]["status"] == "done"


def test_no_names_records_the_marker_and_writes_no_contacts(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "name": "Acme", "website": "https://acme.com"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub(monkeypatch, {"p1": _result("p1", status="no_names")})

    asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert db.tables["prospect_name_scrape"][0]["status"] == "no_names"
    assert db.tables["prospect_contact"] == []


def test_unreachable_is_recorded_not_no_names(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "name": "Acme", "website": "https://acme.com"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub(monkeypatch, {"p1": _result("p1", status="unreachable", fetch_status="blocked")})

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert report.orders[0].unreachable == 1
    marker = db.tables["prospect_name_scrape"][0]
    assert marker["status"] == "unreachable" and marker["fetch_status"] == "blocked"


def test_found_and_no_names_are_skipped_but_unreachable_is_retried(monkeypatch):
    """The idempotency: a durable answer is never re-scraped; an unreachable one is."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "pl-1", "name": "A", "website": "https://a.com"},
            {"id": "p2", "place_id": "pl-2", "name": "B", "website": "https://b.com"},
            {"id": "p3", "place_id": "pl-3", "name": "C", "website": "https://c.com"},
        ],
        orders=[_order(prospect_ids=["p1", "p2", "p3"])],
    )
    db.tables["prospect_name_scrape"] = [
        {"prospect_id": "p1", "status": "found"},
        {"prospect_id": "p2", "status": "unreachable"},  # retryable
    ]
    seen = []

    async def scrape_names(settings, prospects, **_k):
        seen.extend(p["id"] for p in prospects)
        return [_result(p["id"], status="no_names") for p in prospects], []

    monkeypatch.setattr(name_scrape_queue.name_scrape, "scrape_names", scrape_names)

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert sorted(seen) == ["p2", "p3"], "found is skipped; unreachable + never-scraped are done"
    assert report.orders[0].skipped == 1


def test_replace_on_place_keeps_outscraper_contacts(monkeypatch):
    """A re-scrape replaces only this prospect's site_scrape contacts — the Outscraper ones stay."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "pl-1", "name": "A", "website": "https://a.com"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    db.tables["prospect_contact"] = [
        {"id": "os-1", "prospect_id": "p1", "place_id": "pl-1", "source": "outscraper",
         "email": "jane@a.com"},
        {"id": "ss-old", "prospect_id": "p1", "place_id": "pl-1", "source": "site_scrape",
         "full_name": "Stale Name"},
    ]
    # a prior unreachable marker means it is NOT skipped
    db.tables["prospect_name_scrape"] = [{"prospect_id": "p1", "status": "unreachable"}]
    _stub(monkeypatch, {"p1": _result("p1", status="found", names=["Fresh Owner"])})

    asyncio.run(name_scrape_queue.drain(db, _Settings()))

    contacts = db.tables["prospect_contact"]
    outscraper = [c for c in contacts if c["source"] == "outscraper"]
    site = [c for c in contacts if c["source"] == "site_scrape"]
    assert len(outscraper) == 1 and outscraper[0]["email"] == "jane@a.com"  # untouched
    assert [c["full_name"] for c in site] == ["Fresh Owner"]  # replaced, not doubled


def test_the_per_order_ceiling_refuses_rather_than_truncates(monkeypatch):
    settings = _Settings()
    settings.name_scrape_max_places_per_order = 1
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "pl-1", "name": "A", "website": "https://a.com"},
            {"id": "p2", "place_id": "pl-2", "name": "B", "website": "https://b.com"},
        ],
        orders=[_order(prospect_ids=["p1", "p2"])],
    )
    called = []

    async def scrape_names(settings, prospects, **_k):
        called.extend(p["id"] for p in prospects)
        return [], []

    monkeypatch.setattr(name_scrape_queue.name_scrape, "scrape_names", scrape_names)

    report = asyncio.run(name_scrape_queue.drain(db, settings))

    assert called == [], "an over-cap order must refuse, not scrape a subset"
    assert report.orders[0].outcome == "failed" and "exceeds" in report.orders[0].error


def test_a_missing_result_marks_the_prospect_failed(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "pl-1", "name": "A", "website": "https://a.com"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub(monkeypatch, {}, errors=["p1: connection reset"])  # no result for p1

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert report.orders[0].failed == 1
    assert db.tables["prospect_name_scrape"][0]["status"] == "failed"  # retryable


def test_a_prospect_without_a_website_is_not_scraped(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "pl-1", "name": "A", "website": None}],
        orders=[_order(prospect_ids=["p1"])],
    )
    called = []

    async def scrape_names(settings, prospects, **_k):
        called.extend(p["id"] for p in prospects)
        return [], []

    monkeypatch.setattr(name_scrape_queue.name_scrape, "scrape_names", scrape_names)

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert called == [] and report.orders[0].outcome == "done"


def test_drain_processes_several_orders_per_tick(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "pl-1", "name": "A", "website": "https://a.com"},
            {"id": "p2", "place_id": "pl-2", "name": "B", "website": "https://b.com"},
        ],
        orders=[
            _order(id="ord-1", prospect_ids=["p1"], created_at="2026-08-20T01:00:00+00:00"),
            _order(id="ord-2", prospect_ids=["p2"], created_at="2026-08-20T02:00:00+00:00"),
        ],
    )
    _stub(monkeypatch, {
        "p1": _result("p1", status="found", names=["Amy Cole"]),
        "p2": _result("p2", status="found", names=["Ben Diaz"]),
    })

    report = asyncio.run(name_scrape_queue.drain(db, _Settings()))

    assert report.orders_processed == 2
    assert {r["status"] for r in db.tables["name_scrape_request"]} == {"done"}


def test_market_backfill_scrapes_due_prospects(monkeypatch):
    db = _FakeDB()
    db.tables["prospect"] = [
        {"id": "p1", "place_id": "pl-1", "market_id": "m1", "name": "A", "website": "https://a.com"},
        {"id": "p2", "place_id": "pl-2", "market_id": "m1", "name": "B", "website": None},
        {"id": "p3", "place_id": "pl-3", "market_id": "m1", "name": "C", "website": "https://c.com"},
    ]
    db.tables["prospect_name_scrape"] = [{"prospect_id": "p3", "status": "found"}]  # already done
    db.tables["prospect_contact"] = []
    _stub(monkeypatch, {"p1": _result("p1", status="found", names=["Amy Cole"])})

    report = asyncio.run(
        name_scrape_queue.run_name_scrape_market(db, _Settings(), market_id="m1")
    )

    # p1 scraped (has website, not done); p2 has no website; p3 already found → skipped
    assert report.requested == 1 and report.found == 1


# --- command wiring ---------------------------------------------------------------------------


def test_scan_names_is_free_and_the_drain_is_order_gated():
    from api.scripts.run_market import PAID_COMMANDS

    assert "scan-names" not in PAID_COMMANDS
