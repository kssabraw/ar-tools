"""The Enigma card-revenue drain — the gate + idempotency properties, not the plumbing.

This is the per-prospect PAID sibling of `name_search_queue`, storing card windows instead of
contacts, so what's tested here is what MATTERS: a matched entity's 1m/3m/12m windows are stored,
a re-order skips already-fetched prospects (no re-bill), a no-match / no-card is a durable billed
answer (not a failure, not re-billed), a call error is retryable, the per-order + per-tick budgets
bound the tick, and a stuck order is recovered. `enigma_graphql.lookup_many` is stubbed throughout
— its transport behaviour is not the subject.
"""

from types import SimpleNamespace

import asyncio

from api.services import enigma_graphql, enigma_queue


# --- a fake supporting the drain's query shapes (in_/lt/delete/upsert/order) -------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.eqs = []
        self.in_filters = []
        self.lt_filters = []
        self._order = None
        self._limit = None
        self._conflict = None

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

    def lt(self, column, value):
        self.lt_filters.append((column, value))
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
        if not all(row.get(c) in vs for c, vs in self.in_filters):
            return False
        return all(row.get(c) is not None and str(row.get(c)) < str(v) for c, v in self.lt_filters)

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
        if self._limit is not None:
            found = found[: self._limit]
        return _Result([dict(r) for r in found])


class _FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self, name)


class _Settings:
    enigma_entity_type = "brand"
    enigma_chunk_size = 5
    enigma_orders_per_tick = 3
    enigma_max_places_per_order = 200
    enigma_per_tick = 24
    enigma_stuck_order_minutes = 20
    enigma_cost_per_lookup_cents = 50
    max_market_run_cost_cents = 5000


# --- entity fixtures + the lookup_many stub ----------------------------------------------------

_CARD_ENTITY = {
    "names": {"edges": [{"node": {"name": "Acme Plumbing"}}]},
    "cardTransactions": {"edges": [
        {"node": {"period": "1m", "projectedQuantity": 8000, "periodEndDate": "2025-06-30"}},
        {"node": {"period": "3m", "projectedQuantity": 24000, "periodEndDate": "2025-06-30"}},
        {"node": {"period": "12m", "projectedQuantity": 90000, "periodEndDate": "2025-06-30"}},
    ]},
}
_NO_CARD_ENTITY = {"names": {"edges": [{"node": {"name": "Bare Listing LLC"}}]}}


def _seed(db, *, prospects, orders):
    db.tables["prospect"] = [dict(p) for p in prospects]
    db.tables["enigma_request"] = [dict(o) for o in orders]
    db.tables.setdefault("prospect_enigma", [])
    db.tables.setdefault("cost_ledger", [])


def _order(id="ord-1", prospect_ids=("p1",), status="pending", **kw):
    return dict(
        {
            "id": id,
            "prospect_ids": list(prospect_ids),
            "entity_type": "brand",
            "requested_by": "admin-1",
            "status": status,
            "created_at": "2026-08-28T01:00:00+00:00",
        },
        **kw,
    )


def _prospect(pid, name="Acme Plumbing", **kw):
    return dict({"id": pid, "place_id": f"place-{pid}", "market_id": "m1", "name": name,
                 "address": "1 Main St", "website": "https://acme.com"}, **kw)


def _stub_lookup(monkeypatch, by_id, *, sent=None, raises=None):
    """Stub `enigma_graphql.lookup_many`. `by_id` maps prospect_id → an entity dict (a match with that
    entity), None (a clean no-match), or the string 'fail' (a call error). `sent` records the ids the
    stub was actually called with (to assert skips never reach the provider)."""
    async def lookup_many(settings, prospects, *, entity_type="brand", concurrency=5):
        if raises:
            raise raises
        out = []
        for p in prospects:
            pid = p["id"]
            if sent is not None:
                sent.append(pid)
            spec = by_id.get(pid, None)
            if spec == "fail":
                call = SimpleNamespace(ok=False, error="boom", body_text="", status=500)
                out.append(enigma_graphql.GraphqlLookup(prospect_id=pid, biz=p, call=call, brand=None))
            else:
                call = SimpleNamespace(ok=True, error="", body_text="{}", status=200)
                out.append(enigma_graphql.GraphqlLookup(prospect_id=pid, biz=p, call=call, brand=spec))
        return out

    monkeypatch.setattr(enigma_queue.enigma_graphql, "lookup_many", lookup_many)


# --- claiming ----------------------------------------------------------------------------------


def test_only_pending_orders_are_claimed():
    db = _FakeDB()
    _seed(db, prospects=[], orders=[_order(status="done")])
    assert enigma_queue.claim_next_order(db) is None


# --- the drain: the four per-prospect outcomes -------------------------------------------------


def test_a_matched_order_stores_card_and_resolves_done(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY})

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    o = report.orders[0]
    assert o.outcome == "done" and o.matched == 1 and o.card == 1 and o.failed == 0

    order_row = db.tables["enigma_request"][0]
    assert order_row["status"] == "done"
    assert order_row["matched_count"] == 1 and order_row["card_count"] == 1

    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "matched" and row["matched"] is True
    assert row["card_revenue_1m"] == 8000 and row["card_revenue_3m"] == 24000
    assert row["card_revenue_12m"] == 90000
    assert row["card_as_of"] == "2025-06-30"
    assert row["matched_name"] == "Acme Plumbing"
    assert row["raw"] == _CARD_ENTITY          # the untouched entity kept for re-parse
    assert db.tables["cost_ledger"][0]["units"] == 1
    assert db.tables["cost_ledger"][0]["provider"] == "enigma"


def test_a_match_without_card_records_no_card_not_failed(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1", name="Bare Listing LLC")], orders=[_order(prospect_ids=["p1"])])
    _stub_lookup(monkeypatch, {"p1": _NO_CARD_ENTITY})

    asyncio.run(enigma_queue.drain(db, _Settings()))

    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "no_card" and row["matched"] is True
    assert row["card_revenue_12m"] is None
    # a billed, matched answer — counted as matched, not card
    o = db.tables["enigma_request"][0]
    assert o["matched_count"] == 1 and o["card_count"] == 0


def test_a_no_match_is_recorded_and_billed(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    _stub_lookup(monkeypatch, {"p1": None})   # a clean 200 with no matched entity

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "no_match" and row["matched"] is False and row["raw"] is None
    assert report.orders[0].no_match == 1
    assert db.tables["enigma_request"][0]["no_match_count"] == 1
    # it still billed — the search ran
    assert db.tables["cost_ledger"][0]["units"] == 1


def test_a_failed_lookup_is_retryable(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    _stub_lookup(monkeypatch, {"p1": "fail"})

    asyncio.run(enigma_queue.drain(db, _Settings()))

    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "failed"   # NOT durable — a re-order retries it


# --- idempotency: durable answers are never re-billed ------------------------------------------


def test_already_fetched_prospects_are_skipped_not_rebilled(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1"), _prospect("p2")], orders=[_order(prospect_ids=["p1", "p2"])])
    db.tables["prospect_enigma"] = [
        {"prospect_id": "p1", "status": "matched", "matched": True, "card_revenue_12m": 5}
    ]
    sent: list[str] = []
    _stub_lookup(monkeypatch, {"p2": _CARD_ENTITY}, sent=sent)

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    assert sent == ["p2"], "the already-matched prospect must not be re-billed"
    o = report.orders[0]
    assert o.skipped == 1 and o.matched == 1 and o.billable == 1


def test_a_no_match_answer_is_durable_and_not_rebilled(monkeypatch):
    """A prior no_match is a real billed answer — skipped on a re-order, like matched/no_card."""
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    db.tables["prospect_enigma"] = [{"prospect_id": "p1", "status": "no_match", "matched": False}]
    sent: list[str] = []
    _stub_lookup(monkeypatch, {}, sent=sent)

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    assert sent == []
    o = report.orders[0]
    assert o.outcome == "done" and o.skipped == 1 and o.billable == 0
    assert db.tables["cost_ledger"] == []      # nothing billed → no ledger row


def test_a_failed_marker_is_retried_not_skipped(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    db.tables["prospect_enigma"] = [{"prospect_id": "p1", "status": "failed", "matched": False}]
    sent: list[str] = []
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY}, sent=sent)

    asyncio.run(enigma_queue.drain(db, _Settings()))

    assert sent == ["p1"], "a failed marker is retryable and must be re-looked-up"
    assert db.tables["prospect_enigma"][0]["status"] == "matched"


# --- billability + budget ----------------------------------------------------------------------


def test_a_prospect_with_no_name_is_not_looked_up(monkeypatch):
    """Enigma matches on a NAME; a nameless prospect is not billable — counted as missing, not skipped,
    not failed (place_id is deliberately NOT required, unlike the contact rungs)."""
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1", name="  ")], orders=[_order(prospect_ids=["p1"])])
    sent: list[str] = []
    _stub_lookup(monkeypatch, {}, sent=sent)

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    assert sent == []
    o = report.orders[0]
    assert o.outcome == "done" and o.billable == 0
    assert db.tables["prospect_enigma"] == []


def test_the_per_order_ceiling_refuses_rather_than_truncates(monkeypatch):
    settings = _Settings()
    settings.enigma_max_places_per_order = 1
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1"), _prospect("p2")], orders=[_order(prospect_ids=["p1", "p2"])])
    sent: list[str] = []
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY, "p2": _CARD_ENTITY}, sent=sent)

    report = asyncio.run(enigma_queue.drain(db, settings))

    assert sent == [], "an over-cap order must refuse, not silently look up a subset"
    o = report.orders[0]
    assert o.outcome == "failed" and "exceeds" in o.error


def test_the_budget_backstop_runs_before_the_money(monkeypatch):
    settings = _Settings()
    settings.max_market_run_cost_cents = 3      # 1 lookup at 50¢ > 3¢
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    sent: list[str] = []
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY}, sent=sent)

    report = asyncio.run(enigma_queue.drain(db, settings))

    assert sent == []
    assert report.orders[0].outcome == "failed"
    assert db.tables["enigma_request"][0]["status"] == "failed"


def test_the_raw_entity_is_kept_for_reparse(monkeypatch):
    """The untouched matched entity is stored in `raw` so a later owner/firmographic re-parse needs no
    re-bill — the whole reason the deferred contacts rung stays cheap."""
    db = _FakeDB()
    entity = dict(_CARD_ENTITY, roles={"edges": [{"node": {"jobTitle": "OWNER"}}]})
    _seed(db, prospects=[_prospect("p1")], orders=[_order(prospect_ids=["p1"])])
    _stub_lookup(monkeypatch, {"p1": entity})

    asyncio.run(enigma_queue.drain(db, _Settings()))

    assert db.tables["prospect_enigma"][0]["raw"] == entity


# --- batchy drain + wiring ---------------------------------------------------------------------


def test_drain_processes_several_orders_per_tick(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[_prospect("p1"), _prospect("p2")],
        orders=[
            _order(id="ord-1", prospect_ids=["p1"], created_at="2026-08-28T01:00:00+00:00"),
            _order(id="ord-2", prospect_ids=["p2"], created_at="2026-08-28T02:00:00+00:00"),
        ],
    )
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY, "p2": _CARD_ENTITY})

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    assert report.orders_processed == 2
    assert {r["status"] for r in db.tables["enigma_request"]} == {"done"}


def test_max_orders_bounds_the_tick(monkeypatch):
    db = _FakeDB()
    _seed(
        db,
        prospects=[_prospect("p1")],
        orders=[
            _order(id="ord-1", prospect_ids=["p1"], created_at="2026-08-28T01:00:00+00:00"),
            _order(id="ord-2", prospect_ids=["p1"], created_at="2026-08-28T02:00:00+00:00"),
        ],
    )
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY})

    report = asyncio.run(enigma_queue.drain(db, _Settings(), max_orders=1))

    assert report.orders_processed == 1
    assert sorted(r["status"] for r in db.tables["enigma_request"]) == ["done", "pending"]


def test_enigma_is_order_gated_not_env_gated():
    """`enigma` drains signed orders — the order is the confirmation, so it is NOT in PAID_COMMANDS
    (listing it makes every drain refuse for want of a token). `probe-enigma-graphql` IS paid."""
    from api.scripts.run_market import PAID_COMMANDS

    assert "enigma" not in PAID_COMMANDS
    assert "probe-enigma-graphql" in PAID_COMMANDS


def test_a_batch_exception_marks_all_failed_and_retryable(monkeypatch):
    """If the whole lookup_many pass raises (it shouldn't — every prospect is wrapped — but the outer
    guard is belt-and-braces), the batch is marked failed/retryable and the order left resumable."""
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1"), _prospect("p2")], orders=[_order(prospect_ids=["p1", "p2"])])
    _stub_lookup(monkeypatch, {}, raises=RuntimeError("transport died"))

    report = asyncio.run(enigma_queue.drain(db, _Settings()))

    assert report.orders[0].failed == 2
    assert {r["status"] for r in db.tables["prospect_enigma"]} == {"failed"}


# --- I-118: per-tick budget + resume, and stuck-order recovery ---------------------------------


def test_a_large_order_resumes_across_ticks(monkeypatch):
    """An order larger than the per-tick budget is looked up to it and left PENDING; the next tick's
    idempotent skip re-bills only the un-done prospects, until it finishes (I-118)."""
    pids = [f"p{i}" for i in range(5)]
    db = _FakeDB()
    _seed(db, prospects=[_prospect(pid) for pid in pids], orders=[_order(prospect_ids=pids)])
    _stub_lookup(monkeypatch, {pid: _CARD_ENTITY for pid in pids})

    def matched_markers():
        return sum(1 for m in db.tables["prospect_enigma"] if m["status"] == "matched")

    asyncio.run(enigma_queue.drain(db, _Settings(), max_places=2))
    assert db.tables["enigma_request"][0]["status"] == "pending"
    assert matched_markers() == 2

    asyncio.run(enigma_queue.drain(db, _Settings(), max_places=2))
    assert db.tables["enigma_request"][0]["status"] == "pending"
    assert matched_markers() == 4

    asyncio.run(enigma_queue.drain(db, _Settings(), max_places=2))
    order = db.tables["enigma_request"][0]
    assert order["status"] == "done"
    assert order["matched_count"] == 5             # CUMULATIVE, not the last batch
    assert matched_markers() == 5
    # one ledger row per billing tick (3), never a re-bill of a done prospect
    assert sum(r["units"] for r in db.tables["cost_ledger"]) == 5


def test_the_per_tick_budget_bounds_the_tick(monkeypatch):
    """The budget caps prospects across the WHOLE tick (not per order), so several small orders can't
    together overrun the window either."""
    db = _FakeDB()
    _seed(
        db,
        prospects=[_prospect(f"p{i}") for i in range(4)],
        orders=[_order(id="o1", prospect_ids=["p0", "p1"]),
                _order(id="o2", prospect_ids=["p2", "p3"])],
    )
    _stub_lookup(monkeypatch, {f"p{i}": _CARD_ENTITY for i in range(4)})

    asyncio.run(enigma_queue.drain(db, _Settings(), max_places=3))
    assert sum(1 for m in db.tables["prospect_enigma"] if m["status"] == "matched") == 3
    statuses = {o["id"]: o["status"] for o in db.tables["enigma_request"]}
    assert statuses == {"o1": "done", "o2": "pending"}


def test_a_stuck_running_order_is_recovered_and_finished(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")],
          orders=[_order(prospect_ids=["p1"], status="running",
                         started_at="2020-01-01T00:00:00+00:00")])
    _stub_lookup(monkeypatch, {"p1": _CARD_ENTITY})

    asyncio.run(enigma_queue.drain(db, _Settings()))
    assert db.tables["enigma_request"][0]["status"] == "done"


def test_a_recently_running_order_is_not_recovered():
    db = _FakeDB()
    _seed(db, prospects=[_prospect("p1")],
          orders=[_order(prospect_ids=["p1"], status="running", started_at=enigma_queue._now())])
    assert enigma_queue.recover_stuck_orders(db, _Settings()) == 0
    assert db.tables["enigma_request"][0]["status"] == "running"
