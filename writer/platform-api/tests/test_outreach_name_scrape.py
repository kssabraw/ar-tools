"""Pure-logic tests for the FREE site name-scrape placement — no network, no real database.

The name-scrape has no spend gate (it is free), so what's worth pinning is the selection validation
and the NO-OP refusal: a selection where every prospect is already scraped or has no website must be
refused (`nothing_to_scrape`) rather than placing an order that would scrape nobody — the same
"reports clean because it did almost nothing" failure the module guards against.
"""
import pytest

from services import outreach as svc
from services.outreach import OutreachError


# --- selection validation (pure) --------------------------------------------------------------


def test_selection_is_deduped_and_bounded():
    assert svc.validate_name_scrape_selection(["a", "b", "a"], 10) == ["a", "b"]


def test_an_empty_selection_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_name_scrape_selection([], 10)
    assert e.value.code == "empty_selection"


def test_an_over_cap_selection_is_refused_not_truncated():
    with pytest.raises(OutreachError) as e:
        svc.validate_name_scrape_selection(["a", "b", "c"], 2)
    assert e.value.code == "selection_too_large"


# --- a tiny fake outreach client for the actionable / no-op logic ------------------------------


class _Q:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.in_filters = []

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        return _Q(self.db, self.name, "insert", payload)

    def in_(self, col, vals):
        self.in_filters.append((col, list(vals)))
        return self

    def execute(self):
        rows = self.db.tables.get(self.name, [])
        if self.op == "insert":
            written = [dict(self.payload)]
            written[0].setdefault("id", f"{self.name}-1")
            written[0].setdefault("status", "pending")
            return _R(written)
        out = [r for r in rows if all(r.get(c) in vs for c, vs in self.in_filters)]
        return _R([dict(r) for r in out])


class _R:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(self, name)


def _patch(monkeypatch, tables):
    monkeypatch.setattr(svc, "get_outreach_client", lambda: _FakeClient(tables))


def test_actionable_counts_split_done_no_website_and_scrapable(monkeypatch):
    tables = {
        "prospect": [
            {"id": "p1", "website": "https://a.com"},   # scrapable
            {"id": "p2", "website": None},               # no website
            {"id": "p3", "website": "https://c.com"},    # already scraped
        ],
        "prospect_name_scrape": [{"prospect_id": "p3", "status": "found"}],
    }
    _patch(monkeypatch, tables)
    counts = svc._name_scrape_actionable(svc.get_outreach_client(), ["p1", "p2", "p3"])
    assert counts == {"requested": 3, "skippable": 1, "no_website": 1, "actionable": 1}


def test_create_refuses_a_no_op_selection(monkeypatch):
    tables = {
        "prospect": [{"id": "p1", "website": None}],   # nothing to fetch
        "prospect_name_scrape": [],
    }
    _patch(monkeypatch, tables)
    with pytest.raises(OutreachError) as e:
        svc.create_name_scrape_request(prospect_ids=["p1"], note=None, actor_id="staff-1")
    assert e.value.code == "nothing_to_scrape"


def test_create_places_an_order_when_something_is_scrapable(monkeypatch):
    tables = {
        "prospect": [{"id": "p1", "website": "https://a.com"}],
        "prospect_name_scrape": [],
    }
    _patch(monkeypatch, tables)
    order = svc.create_name_scrape_request(prospect_ids=["p1"], note=" find owner ", actor_id="staff-1")
    assert order["status"] == "pending"
    assert order["prospect_ids"] == ["p1"]
    assert order["note"] == "find owner"
    assert order["actionable"]["actionable"] == 1
