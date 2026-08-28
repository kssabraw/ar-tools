"""Pure-logic tests for the PAID web-search placement — no network, no real database.

The name-search bills, so what's worth pinning is the spend gate (selection validation, the
billable computation that excludes already-named/already-searched prospects, the daily-budget
refusal) and the NO-OP refusal (`nothing_to_search`)."""
import pytest

from services import outreach as svc
from services.outreach import OutreachError


# --- selection validation (pure) --------------------------------------------------------------


def test_selection_is_deduped_and_bounded():
    assert svc.validate_name_search_selection(["a", "b", "a"], 10) == ["a", "b"]


def test_empty_and_over_cap_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_name_search_selection([], 10)
    assert e.value.code == "empty_selection"
    with pytest.raises(OutreachError) as e:
        svc.validate_name_search_selection(["a", "b", "c"], 2)
    assert e.value.code == "selection_too_large"


# --- a fake outreach client -------------------------------------------------------------------


class _Not:
    def __init__(self, q):
        self._q = q

    def is_(self, col, _v):
        self._q.not_null.append(col)
        return self._q


class _Q:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.ins = []
        self.not_null = []
        self.not_ = _Not(self)

    def select(self, *_a, **_k):
        return self

    def insert(self, p):
        return _Q(self.db, self.name, "insert", p)

    def in_(self, c, v):
        self.ins.append((c, list(v)))
        return self

    def eq(self, *_a):
        return self

    def gte(self, *_a):
        return self

    def execute(self):
        rows = self.db.tables.get(self.name, [])
        if self.op == "insert":
            w = [dict(self.payload)]
            w[0].setdefault("id", f"{self.name}-1")
            w[0].setdefault("status", "pending")
            return _R(w)
        out = [r for r in rows if all(r.get(c) in vs for c, vs in self.ins)]
        for col in self.not_null:
            out = [r for r in out if r.get(col) is not None]
        return _R([dict(r) for r in out])


class _R:
    def __init__(self, data):
        self.data = data


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(self, name)


def _patch(monkeypatch, tables):
    monkeypatch.setattr(svc, "get_outreach_client", lambda: _Client(tables))


def _base_tables():
    return {
        "prospect": [
            {"id": "p1", "place_id": "pl1"},   # billable (no name, not searched)
            {"id": "p2", "place_id": "pl2"},   # already named
            {"id": "p3", "place_id": "pl3"},   # already searched (no_names)
        ],
        "prospect_name_search": [{"prospect_id": "p3", "status": "no_names"}],
        "prospect_contact": [
            {"prospect_id": "p2", "full_name": "Existing Owner"},
            {"prospect_id": "p1", "full_name": None},  # a phone-only contact, no name
        ],
        "name_search_request": [],
    }


def test_billable_excludes_named_and_searched(monkeypatch):
    _patch(monkeypatch, _base_tables())
    counts = svc._name_search_billable(svc.get_outreach_client(), ["p1", "p2", "p3"])
    assert counts["billable"] == 1              # only p1
    assert counts["already_named"] == 1         # p2
    assert counts["already_searched"] == 1      # p3


def test_create_refuses_when_nothing_billable(monkeypatch):
    _patch(monkeypatch, _base_tables())
    with pytest.raises(OutreachError) as e:
        svc.create_name_search_request(prospect_ids=["p2", "p3"], note=None, actor_id="admin-1")
    assert e.value.code == "nothing_to_search"


def test_create_places_a_paid_order_with_estimate(monkeypatch):
    from config import settings

    _patch(monkeypatch, _base_tables())
    order = svc.create_name_search_request(prospect_ids=["p1"], note=None, actor_id="admin-1")
    assert order["status"] == "pending"
    assert order["est_cost_cents"] == settings.outreach_name_search_cost_cents  # 1 billable × rate
    assert order["estimate"]["billable"] == 1


def test_budget_denial_blocks_placement(monkeypatch):
    tables = _base_tables()
    # a prior order today already at/over the daily budget
    tables["name_search_request"] = [{"est_cost_cents": 100000, "requested_by": "admin-1"}]
    _patch(monkeypatch, tables)
    with pytest.raises(OutreachError) as e:
        svc.create_name_search_request(prospect_ids=["p1"], note=None, actor_id="admin-1")
    assert e.value.code == "name_search_budget_exceeded"
