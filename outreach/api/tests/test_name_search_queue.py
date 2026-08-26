"""The PAID name-search drain. What's tested is the paid discipline (budget backstop, cost_ledger,
idempotent no-re-bill) + the correctness shared with the free drains (replace-on-place scoped to
web_search contacts, per-prospect isolation). `name_search.search_names` is stubbed."""

import asyncio

from api.services import name_search, name_search_queue


# --- fake supporting in_/eq/delete/upsert/insert/update -----------------------------------------


class _R:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.eqs, self.ins = [], []
        self._order = self._limit = self._conflict = None

    def select(self, *_a, **_k):
        return self

    def insert(self, p):
        return _Q(self.db, self.name, "insert", p)

    def update(self, p):
        return _Q(self.db, self.name, "update", p)

    def delete(self):
        return _Q(self.db, self.name, "delete")

    def upsert(self, p, on_conflict=None):
        q = _Q(self.db, self.name, "upsert", p)
        q._conflict = on_conflict
        return q

    def eq(self, c, v):
        self.eqs.append((c, v))
        return self

    def in_(self, c, v):
        self.ins.append((c, list(v)))
        return self

    def order(self, c, desc=False):
        self._order = (c, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _match(self, r):
        return (all(str(r.get(c)) == str(v) for c, v in self.eqs)
                and all(r.get(c) in vs for c, vs in self.ins))

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = [dict(r) for r in payload]
            for i, r in enumerate(written):
                r.setdefault("id", f"{self.name}-{len(rows) + i}")
            rows.extend(written)
            return _R(written)
        if self.op == "upsert":
            hit = next((r for r in rows if r.get(self._conflict) == self.payload.get(self._conflict)), None)
            if hit:
                hit.update(self.payload)
                return _R([dict(hit)])
            new = dict(self.payload)
            new.setdefault("id", f"{self.name}-{len(rows)}")
            rows.append(new)
            return _R([dict(new)])
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return _R([dict(r) for r in hit])
        if self.op == "delete":
            keep = [r for r in rows if not self._match(r)]
            self.db.tables[self.name] = keep
            return _R([{"removed": len(rows) - len(keep)}])
        found = [r for r in rows if self._match(r)]
        if self._order:
            c, d = self._order
            found = sorted(found, key=lambda r: str(r.get(c) or ""), reverse=d)
        if self._limit is not None:
            found = found[: self._limit]
        return _R([dict(r) for r in found])


class _FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Q(self, name)


class _Settings:
    name_search_cost_cents = 3
    name_search_chunk_size = 4
    name_search_orders_per_tick = 5
    name_search_max_places_per_order = 100
    max_market_run_cost_cents = 5000


def _seed(db, *, prospects, orders):
    db.tables["prospect"] = [dict(p) for p in prospects]
    db.tables["name_search_request"] = [dict(o) for o in orders]
    db.tables.setdefault("prospect_name_search", [])
    db.tables.setdefault("prospect_contact", [])
    db.tables.setdefault("cost_ledger", [])


def _order(id="ord-1", prospect_ids=("p1",), status="pending", **kw):
    return dict({"id": id, "prospect_ids": list(prospect_ids), "requested_by": "admin-1",
                 "status": status, "created_at": "2026-08-26T01:00:00+00:00"}, **kw)


def _result(pid, *, status, name=None, citation="https://x.com/o"):
    names = ()
    if name:
        names = (name_search.SearchedName(full_name=name, title="Owner", citation=citation,
                                          evidence="web search", first_name=name.split()[0],
                                          last_name=name.split()[-1]),)
    return name_search.NameSearchResult(prospect_id=pid, status=status, names=names,
                                        model="gpt-5.4",
                                        citations=(citation,) if name else (), raw={"text": ""})


def _stub(monkeypatch, by_id, errors=None, raises=None):
    async def search_names(settings, prospects, **_k):
        if raises:
            raise raises
        return [by_id[p["id"]] for p in prospects if p["id"] in by_id], list(errors or [])
    monkeypatch.setattr(name_search_queue.name_search, "search_names", search_names)


def test_only_pending_claimed():
    db = _FakeDB()
    _seed(db, prospects=[], orders=[_order(status="done")])
    assert name_search_queue.claim_next_order(db) is None


def test_found_stores_web_search_contact_ledger_and_done(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "Acme"}],
          orders=[_order(prospect_ids=["p1"])])
    _stub(monkeypatch, {"p1": _result("p1", status="found", name="Bob Lee")})

    report = asyncio.run(name_search_queue.drain(db, _Settings()))

    o = report.orders[0]
    assert o.outcome == "done" and o.found == 1 and o.names == 1 and o.billable == 1
    c = db.tables["prospect_contact"]
    assert len(c) == 1 and c[0]["source"] == "web_search" and c[0]["full_name"] == "Bob Lee"
    assert c[0]["raw"]["citation"] == "https://x.com/o"
    assert db.tables["prospect_name_search"][0]["status"] == "found"
    assert db.tables["cost_ledger"][0]["units"] == 1 and db.tables["cost_ledger"][0]["provider"] == "openai"
    assert db.tables["name_search_request"][0]["status"] == "done"


def test_no_names_still_bills(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "Acme"}],
          orders=[_order(prospect_ids=["p1"])])
    _stub(monkeypatch, {"p1": _result("p1", status="no_names")})

    asyncio.run(name_search_queue.drain(db, _Settings()))

    assert db.tables["prospect_name_search"][0]["status"] == "no_names"
    assert db.tables["prospect_contact"] == []
    assert db.tables["cost_ledger"][0]["units"] == 1  # a search ran → billed even with no name


def test_already_searched_is_not_rebilled(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"},
                         {"id": "p2", "place_id": "pl2", "market_id": "m1", "name": "B"}],
          orders=[_order(prospect_ids=["p1", "p2"])])
    db.tables["prospect_name_search"] = [{"prospect_id": "p1", "status": "no_names"}]
    sent = []

    async def search_names(settings, prospects, **_k):
        sent.extend(p["id"] for p in prospects)
        return [_result("p2", status="found", name="Ben Diaz")], []
    monkeypatch.setattr(name_search_queue.name_search, "search_names", search_names)

    report = asyncio.run(name_search_queue.drain(db, _Settings()))
    assert sent == ["p2"] and report.orders[0].skipped == 1 and report.orders[0].billable == 1


def test_replace_on_place_keeps_other_sources(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"}],
          orders=[_order(prospect_ids=["p1"])])
    db.tables["prospect_contact"] = [
        {"id": "os", "prospect_id": "p1", "place_id": "pl1", "source": "outscraper", "email": "a@a.com"},
        {"id": "ss", "prospect_id": "p1", "place_id": "pl1", "source": "site_scrape", "full_name": "Site Name"},
        {"id": "wsold", "prospect_id": "p1", "place_id": "pl1", "source": "web_search", "full_name": "Old Web"},
    ]
    db.tables["prospect_name_search"] = [{"prospect_id": "p1", "status": "failed"}]  # retryable
    _stub(monkeypatch, {"p1": _result("p1", status="found", name="Fresh Web")})

    asyncio.run(name_search_queue.drain(db, _Settings()))

    by_src = {c["source"]: c for c in db.tables["prospect_contact"]}
    assert by_src["outscraper"]["email"] == "a@a.com"       # untouched
    assert by_src["site_scrape"]["full_name"] == "Site Name"  # untouched
    assert by_src["web_search"]["full_name"] == "Fresh Web"   # replaced, not doubled
    assert sum(1 for c in db.tables["prospect_contact"] if c["source"] == "web_search") == 1


def test_over_cap_refuses(monkeypatch):
    settings = _Settings()
    settings.name_search_max_places_per_order = 1
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"},
                         {"id": "p2", "place_id": "pl2", "market_id": "m1", "name": "B"}],
          orders=[_order(prospect_ids=["p1", "p2"])])
    called = []

    async def search_names(settings, prospects, **_k):
        called.extend(p["id"] for p in prospects)
        return [], []
    monkeypatch.setattr(name_search_queue.name_search, "search_names", search_names)

    report = asyncio.run(name_search_queue.drain(db, settings))
    assert called == [] and report.orders[0].outcome == "failed" and "exceeds" in report.orders[0].error


def test_budget_backstop_runs_before_the_money(monkeypatch):
    settings = _Settings()
    settings.max_market_run_cost_cents = 2  # 1 search at 3c > 2c
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"}],
          orders=[_order(prospect_ids=["p1"])])
    called = []

    async def search_names(settings, prospects, **_k):
        called.extend(p["id"] for p in prospects)
        return [], []
    monkeypatch.setattr(name_search_queue.name_search, "search_names", search_names)

    report = asyncio.run(name_search_queue.drain(db, settings))
    assert called == [] and report.orders[0].outcome == "failed"
    assert db.tables["name_search_request"][0]["status"] == "failed"
    assert db.tables["cost_ledger"] == []  # nothing billed → no ledger row


def test_a_chunk_error_marks_failed_retryable(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"}],
          orders=[_order(prospect_ids=["p1"])])
    _stub(monkeypatch, {}, errors=["p1: provider 500"])

    report = asyncio.run(name_search_queue.drain(db, _Settings()))
    assert report.orders[0].failed == 1
    assert db.tables["prospect_name_search"][0]["status"] == "failed"


def test_drain_several_orders_per_tick(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"},
                         {"id": "p2", "place_id": "pl2", "market_id": "m1", "name": "B"}],
          orders=[_order(id="o1", prospect_ids=["p1"], created_at="2026-08-26T01:00:00+00:00"),
                  _order(id="o2", prospect_ids=["p2"], created_at="2026-08-26T02:00:00+00:00")])
    _stub(monkeypatch, {"p1": _result("p1", status="found", name="Amy Cole"),
                        "p2": _result("p2", status="found", name="Ben Diaz")})

    report = asyncio.run(name_search_queue.drain(db, _Settings()))
    assert report.orders_processed == 2
    assert {r["status"] for r in db.tables["name_search_request"]} == {"done"}
