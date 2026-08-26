"""The Enigma-order drain — the gate, the idempotency, the budget backstop, and gated-inert.

`enigma_client.match_prospects` is stubbed throughout (its transport is not the subject), and the
fake Supabase from test_enrich_queue is reused. What's tested is what the drain guarantees: it does
nothing without a key, skips already-resolved prospects (no re-bill), refuses over budget, stores a
below-gate match as no_match, and records a per-prospect failure as retryable.
"""
import asyncio

from api.services import enigma_queue
from api.tests.test_enrich_queue import _FakeDB


def _run(coro):
    return asyncio.run(coro)


class _Settings:
    enigma_api_key = "k"
    enigma_cost_per_prospect_cents = 15
    enigma_chunk_size = 8
    enigma_orders_per_tick = 3
    enigma_max_prospects_per_order = 200
    enigma_min_match_score = 0.7
    max_market_run_cost_cents = 5000


def _settings(**over):
    s = _Settings()
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _seed(db, *, prospects, orders, resolved=()):
    db.tables["prospect"] = [dict(p) for p in prospects]
    db.tables["enigma_request"] = [dict(o) for o in orders]
    db.tables["prospect_enigma"] = [dict(r) for r in resolved]
    db.tables.setdefault("cost_ledger", [])


def _order(id="ord-1", prospect_ids=("p1",), status="pending", **kw):
    return dict({"id": id, "prospect_ids": list(prospect_ids), "requested_by": "admin-1",
                 "status": status, "created_at": "2026-08-14T01:00:00+00:00"}, **kw)


def _prospect(id="p1", **kw):
    return dict({"id": id, "place_id": f"pl-{id}", "market_id": "m1", "name": "ABC Plumbing",
                 "address": "1 Main St, Anaheim, CA 92801", "phone": "714-555-1234",
                 "website": "abcplumbing.com"}, **kw)


def _resolving_raw():
    return {"data": {"search": [{
        "id": "brand-1",
        "names": {"edges": [{"node": {"name": "ABC Plumbing"}}]},
        "cardRevenueAmount": 1800000, "cardRevenueGrowth": 24.0, "locationCount": 1,
        "phone": "714-555-1234", "website": "abcplumbing.com",
        "legalEntities": {"edges": [{"node": {"people": {"edges": [
            {"node": {"fullName": "John Smith", "title": "Managing Member",
                      "email": "john@abcplumbing.com", "phone": "714-555-9876"}}
        ]}}}]},
    }]}}


def _low_match_raw():
    return {"data": {"search": [{
        "id": "brand-2", "names": {"edges": [{"node": {"name": "Zeta Roofing"}}]},
        "legalEntities": {"edges": [{"node": {"people": {"edges": [
            {"node": {"fullName": "Someone Else", "title": "Owner", "phone": "111"}}]}}}]},
    }]}}


def _stub_match(monkeypatch, *, results=None, errors=None, calls=None):
    async def match_prospects(settings, prospects, *, client=None):
        if calls is not None:
            calls.append([p["id"] for p in prospects])
        return list(results or []), list(errors or [])
    monkeypatch.setattr(enigma_queue.enigma_client, "match_prospects", match_prospects)


def test_gated_off_when_no_key(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()])
    calls: list = []
    _stub_match(monkeypatch, calls=calls)

    report = _run(enigma_queue.drain(db, _settings(enigma_api_key="")))
    assert report.orders_processed == 0
    assert calls == []                                       # never even claimed an order
    assert db.tables["enigma_request"][0]["status"] == "pending"   # left untouched


def test_happy_path_resolves_owner_and_stores(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()])
    _stub_match(monkeypatch, results=[("p1", _resolving_raw())])

    report = _run(enigma_queue.drain(db, _settings()))
    order = report.orders[0]
    assert order.outcome == "done"
    assert (order.resolved, order.owners, order.contacts) == (1, 1, 1)

    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "resolved"
    assert row["owner_name"] == "John Smith" and row["owner_evidence"] == "both"
    assert db.tables["enigma_request"][0]["status"] == "done"
    assert len(db.tables["cost_ledger"]) == 1                # billed the one resolved business


def test_idempotent_skip_does_not_rebill(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()],
          resolved=[{"prospect_id": "p1", "place_id": "pl-p1", "status": "resolved"}])
    calls: list = []
    _stub_match(monkeypatch, results=[("p1", _resolving_raw())], calls=calls)

    report = _run(enigma_queue.drain(db, _settings()))
    order = report.orders[0]
    assert order.outcome == "done" and order.skipped == 1 and order.billable == 0
    assert calls == []                                        # a resolved prospect is never re-matched
    assert db.tables["cost_ledger"] == []                     # and never re-billed


def test_over_budget_fails_with_nothing_spent(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()])
    calls: list = []
    _stub_match(monkeypatch, results=[("p1", _resolving_raw())], calls=calls)

    report = _run(enigma_queue.drain(db, _settings(max_market_run_cost_cents=1)))
    order = report.orders[0]
    assert order.outcome == "failed" and "exceed" in order.error.lower()
    assert calls == []                                        # refused before the paid call
    assert db.tables["enigma_request"][0]["status"] == "failed"


def test_below_gate_is_stored_no_match(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()])
    _stub_match(monkeypatch, results=[("p1", _low_match_raw())])

    report = _run(enigma_queue.drain(db, _settings()))
    order = report.orders[0]
    assert order.outcome == "done" and order.owners == 0 and order.resolved == 0
    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "no_match" and row.get("owner_name") is None


def test_per_prospect_failure_is_retryable(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[_prospect()], orders=[_order()])
    _stub_match(monkeypatch, results=[], errors=["p1: HTTP 500"])

    report = _run(enigma_queue.drain(db, _settings()))
    order = report.orders[0]
    assert order.failed == 1
    row = db.tables["prospect_enigma"][0]
    assert row["status"] == "failed"                          # not a terminal no_match — a re-order retries it
