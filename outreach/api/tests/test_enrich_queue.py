"""The enrichment-order drain — the properties of the gate and the idempotency, not the plumbing.

Enrichment is the batchable sibling of the scan drain, so what's tested here is what DIFFERS: a
re-order skips already-enriched prospects (no re-bill), a chunk failure marks only that chunk
retryable while the rest still store, the per-order budget backstop, and contacts stored
replace-on-place. `enrich_client.enrich_places` is stubbed throughout — its own transport behaviour
is not the subject.
"""

import asyncio

import pytest

from api.services import enrich_client, enrich_queue


# --- a fake supporting the drain's query shapes (in_/not_.is_/delete/upsert) -------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Not:
    def __init__(self, q):
        self._q = q

    def is_(self, column, _value):
        # only used as a no-op sentinel filter in these tests
        return self._q


class _Query:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.eqs = []
        self.in_filters = []
        self._order = None
        self._limit = None
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
            removed = len(rows) - len(keep)
            self.db.tables[self.name] = keep
            return _Result([{"removed": removed}])
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
    enrich_enrichments = ["emails_validator_service", "phones_enricher_service"]
    enrich_cost_per_place_cents = 5
    enrich_chunk_size = 10
    enrich_orders_per_tick = 5
    enrich_max_places_per_order = 200
    max_market_run_cost_cents = 5000


def _seed(db, *, prospects, orders):
    db.tables["prospect"] = [dict(p) for p in prospects]
    db.tables["enrichment_request"] = [dict(o) for o in orders]
    db.tables.setdefault("prospect_enrichment", [])
    db.tables.setdefault("prospect_contact", [])
    db.tables.setdefault("cost_ledger", [])


def _order(id="ord-1", prospect_ids=("p1",), status="pending", **kw):
    return dict(
        {
            "id": id,
            "prospect_ids": list(prospect_ids),
            "enrichments": ["emails_validator_service"],
            "requested_by": "admin-1",
            "status": status,
            "created_at": "2026-08-10T01:00:00+00:00",
        },
        **kw,
    )


def _stub_enrich(monkeypatch, by_place=None, errors=None, raises=None):
    async def enrich_places(settings, place_ids, *, enrichments, client=None):
        if raises:
            raise raises
        records = []
        for pid in place_ids:
            for rec in (by_place or {}).get(pid, []):
                r = dict(rec)
                r[enrich_client.PLACE_TAG] = pid
                records.append(r)
        return records, list(errors or [])

    monkeypatch.setattr(enrich_queue.enrich_client, "enrich_places", enrich_places)


# --- pure helpers -----------------------------------------------------------------------------


def test_error_place_ids_parses_the_prefix():
    assert enrich_queue.error_place_ids(["abc: boom", "def: nope"]) == {"abc", "def"}
    assert enrich_queue.error_place_ids([]) == set()


def test_enrich_place_intersection_is_scoped_to_the_chunk():
    errors = ["p1: timeout", "p9: timeout"]
    assert enrich_queue.enrich_place_intersection(errors, ["p1", "p2"]) == {"p1"}


# --- claiming ---------------------------------------------------------------------------------


def test_only_pending_orders_are_claimed():
    db = _FakeDB()
    _seed(db, prospects=[], orders=[_order(status="done")])
    assert enrich_queue.claim_next_order(db) is None


# --- the drain --------------------------------------------------------------------------------


def test_a_successful_order_stores_contacts_and_resolves_done(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "Acme"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub_enrich(
        monkeypatch,
        by_place={"place-1": [{"emails": [{"value": "jane@acme.com"}, {"value": "info@acme.com"}]}]},
    )

    report = asyncio.run(enrich_queue.drain(db, _Settings()))

    assert report.orders_processed == 1
    o = report.orders[0]
    assert o.outcome == "done"
    assert o.enriched == 1 and o.contacts == 2 and o.failed == 0

    order_row = db.tables["enrichment_request"][0]
    assert order_row["status"] == "done"
    assert order_row["contact_count"] == 2 and order_row["enriched_count"] == 1

    contacts = db.tables["prospect_contact"]
    assert len(contacts) == 2
    enr = db.tables["prospect_enrichment"][0]
    assert enr["status"] == "enriched" and enr["contact_count"] == 2
    # cost ledger recorded the billed place
    assert db.tables["cost_ledger"][0]["units"] == 1


def test_a_place_with_no_contacts_records_no_contacts_not_failed(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "Acme"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub_enrich(monkeypatch, by_place={"place-1": [{"category": "plumber"}]})

    asyncio.run(enrich_queue.drain(db, _Settings()))

    enr = db.tables["prospect_enrichment"][0]
    assert enr["status"] == "no_contacts" and enr["contact_count"] == 0
    assert db.tables["prospect_contact"] == []


def test_already_enriched_prospects_are_skipped_not_rebilled(monkeypatch):
    """The idempotency that makes a re-order a cheap resume: a prospect already enriched (or
    no_contacts) is never sent to the provider again."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"},
            {"id": "p2", "place_id": "place-2", "market_id": "m1", "name": "B"},
        ],
        orders=[_order(prospect_ids=["p1", "p2"])],
    )
    db.tables["prospect_enrichment"] = [
        {"prospect_id": "p1", "place_id": "place-1", "status": "enriched", "contact_count": 1}
    ]
    sent = []

    async def enrich_places(settings, place_ids, *, enrichments, client=None):
        sent.extend(place_ids)
        return [{"emails": [{"value": "b@x.com"}], enrich_client.PLACE_TAG: "place-2"}], []

    monkeypatch.setattr(enrich_queue.enrich_client, "enrich_places", enrich_places)

    report = asyncio.run(enrich_queue.drain(db, _Settings()))

    assert sent == ["place-2"], "the already-enriched place must not be re-billed"
    o = report.orders[0]
    assert o.skipped == 1 and o.enriched == 1 and o.billable == 1


def test_a_fully_skipped_order_is_a_clean_no_op(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    db.tables["prospect_enrichment"] = [
        {"prospect_id": "p1", "place_id": "place-1", "status": "no_contacts", "contact_count": 0}
    ]
    sent = []

    async def enrich_places(settings, place_ids, *, enrichments, client=None):
        sent.extend(place_ids)
        return [], []

    monkeypatch.setattr(enrich_queue.enrich_client, "enrich_places", enrich_places)

    report = asyncio.run(enrich_queue.drain(db, _Settings()))

    assert sent == []
    o = report.orders[0]
    assert o.outcome == "done" and o.skipped == 1 and o.billable == 0
    assert db.tables["enrichment_request"][0]["status"] == "done"
    # nothing billed → no ledger row
    assert db.tables["cost_ledger"] == []


def test_a_chunk_error_marks_those_places_failed_and_retryable(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    _stub_enrich(monkeypatch, by_place={}, errors=["place-1: quota exceeded"])

    report = asyncio.run(enrich_queue.drain(db, _Settings()))

    o = report.orders[0]
    assert o.failed == 1 and o.enriched == 0
    enr = db.tables["prospect_enrichment"][0]
    assert enr["status"] == "failed"  # retryable — a re-order will try it again


def test_the_per_order_ceiling_refuses_rather_than_truncates(monkeypatch):
    settings = _Settings()
    settings.enrich_max_places_per_order = 1
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"},
            {"id": "p2", "place_id": "place-2", "market_id": "m1", "name": "B"},
        ],
        orders=[_order(prospect_ids=["p1", "p2"])],
    )
    called = []

    async def enrich_places(settings, place_ids, *, enrichments, client=None):
        called.extend(place_ids)
        return [], []

    monkeypatch.setattr(enrich_queue.enrich_client, "enrich_places", enrich_places)

    report = asyncio.run(enrich_queue.drain(db, settings))

    assert called == [], "an over-cap order must refuse, not silently enrich a subset"
    o = report.orders[0]
    assert o.outcome == "failed" and "exceeds" in o.error


def test_the_budget_backstop_runs_before_the_money(monkeypatch):
    settings = _Settings()
    settings.max_market_run_cost_cents = 3  # 1 place at 5¢ = 5¢ > 3¢
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    called = []

    async def enrich_places(settings, place_ids, *, enrichments, client=None):
        called.extend(place_ids)
        return [], []

    monkeypatch.setattr(enrich_queue.enrich_client, "enrich_places", enrich_places)

    report = asyncio.run(enrich_queue.drain(db, settings))

    assert called == []
    assert report.orders[0].outcome == "failed"
    assert db.tables["enrichment_request"][0]["status"] == "failed"


def test_re_enrich_replaces_contacts_rather_than_duplicating(monkeypatch):
    """Replace-on-place: a prospect whose prior enrichment FAILED (so it is not skipped) re-enriches
    to a fresh contact set, never a doubled one."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"}],
        orders=[_order(prospect_ids=["p1"])],
    )
    db.tables["prospect_enrichment"] = [
        {"prospect_id": "p1", "place_id": "place-1", "status": "failed", "contact_count": 0}
    ]
    db.tables["prospect_contact"] = [
        {"id": "old", "prospect_id": "p1", "place_id": "place-1", "email": "stale@x.com"}
    ]
    _stub_enrich(monkeypatch, by_place={"place-1": [{"emails": [{"value": "fresh@x.com"}]}]})

    asyncio.run(enrich_queue.drain(db, _Settings()))

    emails = [c.get("email") for c in db.tables["prospect_contact"]]
    assert emails == ["fresh@x.com"], "the stale contact must be replaced, not accumulated"


def test_drain_processes_several_orders_per_tick(monkeypatch):
    """The batchable difference from the scan drain: many orders per heartbeat."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[
            {"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"},
            {"id": "p2", "place_id": "place-2", "market_id": "m1", "name": "B"},
        ],
        orders=[
            _order(id="ord-1", prospect_ids=["p1"], created_at="2026-08-10T01:00:00+00:00"),
            _order(id="ord-2", prospect_ids=["p2"], created_at="2026-08-10T02:00:00+00:00"),
        ],
    )
    _stub_enrich(
        monkeypatch,
        by_place={
            "place-1": [{"emails": [{"value": "a@x.com"}]}],
            "place-2": [{"emails": [{"value": "b@x.com"}]}],
        },
    )

    report = asyncio.run(enrich_queue.drain(db, _Settings()))

    assert report.orders_processed == 2
    assert all(o.outcome == "done" for o in report.orders)
    assert {r["status"] for r in db.tables["enrichment_request"]} == {"done"}


def test_max_orders_bounds_the_tick(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[{"id": "p1", "place_id": "place-1", "market_id": "m1", "name": "A"}],
        orders=[
            _order(id="ord-1", prospect_ids=["p1"], created_at="2026-08-10T01:00:00+00:00"),
            _order(id="ord-2", prospect_ids=["p1"], created_at="2026-08-10T02:00:00+00:00"),
        ],
    )
    _stub_enrich(monkeypatch, by_place={"place-1": [{"emails": [{"value": "a@x.com"}]}]})

    report = asyncio.run(enrich_queue.drain(db, _Settings(), max_orders=1))

    assert report.orders_processed == 1
    statuses = sorted(r["status"] for r in db.tables["enrichment_request"])
    assert statuses == ["done", "pending"]


# --- command wiring ---------------------------------------------------------------------------


def test_enrich_is_order_gated_not_env_gated():
    """`enrich` drains signed orders — the order is the confirmation, so it is NOT in PAID_COMMANDS
    (listing it makes every drain refuse for want of a token). `probe-enrich` IS paid (a live spike)."""
    from api.scripts.run_market import PAID_COMMANDS

    assert "enrich" not in PAID_COMMANDS
    assert "probe-enrich" in PAID_COMMANDS
