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
        self.eqs, self.ins, self.lts = [], [], []
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

    def lt(self, c, v):
        self.lts.append((c, v))
        return self

    def order(self, c, desc=False):
        self._order = (c, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _match(self, r):
        return (all(str(r.get(c)) == str(v) for c, v in self.eqs)
                and all(r.get(c) in vs for c, vs in self.ins)
                and all(r.get(c) is not None and str(r.get(c)) < str(v) for c, v in self.lts))

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
    name_search_per_tick = 24
    name_search_stuck_order_minutes = 20
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


def _result(pid, *, status, name=None, citation="https://x.com/o", model_confidence=None,
            citations=None):
    names = ()
    if name:
        names = (name_search.SearchedName(full_name=name, title="Owner", citation=citation,
                                          evidence="web search", first_name=name.split()[0],
                                          last_name=name.split()[-1], model_confidence=model_confidence),)
    cites = tuple(citations) if citations is not None else ((citation,) if name else ())
    return name_search.NameSearchResult(prospect_id=pid, status=status, names=names,
                                        model="gpt-5.4", citations=cites, raw={"text": ""})


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
    # a blended confidence rides the contact (1 citation, no website, no model → deterministic 40/low)
    assert c[0]["confidence"] == 40 and c[0]["confidence_band"] == "low"
    assert db.tables["prospect_name_search"][0]["status"] == "found"
    assert db.tables["cost_ledger"][0]["units"] == 1 and db.tables["cost_ledger"][0]["provider"] == "openai"
    assert db.tables["name_search_request"][0]["status"] == "done"


def test_confidence_blends_model_rating_and_corroboration(monkeypatch):
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "Acme",
                          "website": "https://acme.com"}],
          orders=[_order(prospect_ids=["p1"])])
    # 3 distinct domains (one is the business's own) + a confident model → High.
    _stub(monkeypatch, {"p1": _result(
        "p1", status="found", name="Bob Lee", model_confidence=90,
        citations=["https://acme.com/about", "https://news.example/x", "https://directory.example/y"])})

    asyncio.run(name_search_queue.drain(db, _Settings()))

    c = db.tables["prospect_contact"][0]
    # deterministic 40 + 20 (3 domains) + 10 (own domain) = 70; blend 0.65*70 + 0.35*90 = 77 → high
    assert c["confidence"] == 77 and c["confidence_band"] == "high"
    assert c["raw"]["model_confidence"] == 90


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


# --- I-118 sibling: per-tick place budget + resume, and stuck-order recovery ------------------


def test_a_large_order_resumes_across_ticks(monkeypatch):
    """An order larger than the per-tick place budget is searched up to it and left PENDING; the next
    tick's idempotent skip re-bills only the un-done places, until it finishes — bounding a big paid
    order to the cron window instead of overrunning it (I-118 sibling)."""
    pids = [f"p{i}" for i in range(5)]
    db = _FakeDB()
    _seed(db, prospects=[{"id": pid, "place_id": f"pl{i}", "market_id": "m1", "name": "A"}
                         for i, pid in enumerate(pids)],
          orders=[_order(prospect_ids=pids)])
    _stub(monkeypatch, {pid: _result(pid, status="found", name=f"Name{i}")
                        for i, pid in enumerate(pids)})

    def found_markers():
        return sum(1 for m in db.tables["prospect_name_search"] if m["status"] == "found")

    asyncio.run(name_search_queue.drain(db, _Settings(), max_places=2))
    assert db.tables["name_search_request"][0]["status"] == "pending"   # partial → resumes
    assert found_markers() == 2

    asyncio.run(name_search_queue.drain(db, _Settings(), max_places=2))
    assert db.tables["name_search_request"][0]["status"] == "pending"
    assert found_markers() == 4

    asyncio.run(name_search_queue.drain(db, _Settings(), max_places=2))
    order = db.tables["name_search_request"][0]
    assert order["status"] == "done"                                   # all 5 done
    assert order["found_count"] == 5 and order["name_count"] == 5      # CUMULATIVE, not last batch
    assert found_markers() == 5
    # one cost_ledger row per tick that billed (3 ticks), never a re-bill of a done place
    assert sum(r["units"] for r in db.tables["cost_ledger"]) == 5


def test_the_per_tick_place_budget_bounds_the_tick(monkeypatch):
    """The budget caps places across the WHOLE tick (not per order), so several small paid orders
    can't together overrun the window either."""
    db = _FakeDB()
    _seed(db, prospects=[{"id": f"p{i}", "place_id": f"pl{i}", "market_id": "m1", "name": "A"}
                         for i in range(4)],
          orders=[_order(id="o1", prospect_ids=["p0", "p1"], created_at="2026-08-26T01:00:00+00:00"),
                  _order(id="o2", prospect_ids=["p2", "p3"], created_at="2026-08-26T02:00:00+00:00")])
    _stub(monkeypatch, {f"p{i}": _result(f"p{i}", status="found", name=f"Name{i}") for i in range(4)})

    asyncio.run(name_search_queue.drain(db, _Settings(), max_places=3))
    # 3 places is the budget: o1 (2) fully, then o2 partial (1) → o2 left pending, loop stops.
    assert sum(1 for m in db.tables["prospect_name_search"] if m["status"] == "found") == 3
    assert {o["id"]: o["status"] for o in db.tables["name_search_request"]} == {"o1": "done", "o2": "pending"}


def test_a_stuck_running_order_is_recovered_and_finished(monkeypatch):
    """A `running` order older than the threshold (its container died mid-tick) is reset to `pending`
    and resumed — the recovery half (I-118 sibling; this producer had no reaper before)."""
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"}],
          orders=[_order(prospect_ids=["p1"], status="running",
                         started_at="2020-01-01T00:00:00+00:00")])
    _stub(monkeypatch, {"p1": _result("p1", status="found", name="Bob Lee")})

    asyncio.run(name_search_queue.drain(db, _Settings()))
    assert db.tables["name_search_request"][0]["status"] == "done"   # recovered → claimed → searched


def test_a_recently_running_order_is_not_recovered():
    """A `running` order younger than the threshold is a live tick's work — never reset (that would
    double-process it, re-billing a paid search)."""
    db = _FakeDB()
    _seed(db, prospects=[{"id": "p1", "place_id": "pl1", "market_id": "m1", "name": "A"}],
          orders=[_order(prospect_ids=["p1"], status="running", started_at=name_search_queue._now())])
    recovered = name_search_queue.recover_stuck_orders(db, _Settings())
    assert recovered == 0
    assert db.tables["name_search_request"][0]["status"] == "running"
