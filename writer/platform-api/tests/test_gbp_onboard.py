"""Bulk GBP onboarding: resolve once, match each client, register + backfill.

The Google resolve, the DB reads, and register/backfill are stubbed at their
seams; the test pins the match → register → skip decisions.
"""

from __future__ import annotations

import types

from services import gbp_locations_service as svc


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _Supa:
    def __init__(self, clients, registered):
        self._clients = clients
        self._registered = registered

    def table(self, name):
        if name == "clients":
            return _Q(self._clients)
        if name == "gbp_locations":
            return _Q(self._registered)
        return _Q([])


def test_onboard_eligible_clients(monkeypatch):
    locations = [
        {"location_id": "locations/111", "account_id": "accounts/1", "place_id": "PID-A",
         "title": "Acme Plumbing", "maps_uri": None, "lat": None, "lng": None},
    ]
    monkeypatch.setattr(svc, "resolve_connected_locations",
                        lambda: {"locations": locations, "detail": None})

    clients = [
        {"id": "c1", "name": "Acme Plumbing", "gbp": {"business_name": "Acme Plumbing"}, "gbp_place_id": "PID-A"},  # exact
        {"id": "c2", "name": "No GBP Co", "gbp": None, "gbp_place_id": None},  # ignored
        {"id": "c3", "name": "Ghost", "gbp": {"business_name": "Totally Unrelated"}, "gbp_place_id": "PID-X"},  # no match
    ]
    monkeypatch.setattr(svc, "get_supabase", lambda: _Supa(clients, []))

    reg_calls: list[tuple] = []
    monkeypatch.setattr(svc, "register_location",
                        lambda *a, **k: (reg_calls.append(a) or {"id": f"row-{a[0]}"}))
    bf_calls: list[str] = []
    monkeypatch.setattr(svc, "_enqueue_backfill", lambda supabase, rid: bf_calls.append(rid))

    result = svc.onboard_eligible_clients(user_id="u1")

    assert result["resolved"] == 1
    assert {o["name"] for o in result["onboarded"]} == {"Acme Plumbing"}
    assert result["onboarded"][0]["location_id"] == "locations/111"
    assert len(reg_calls) == 1 and reg_calls[0][0] == "c1"  # register_location(client_id, ...)
    assert bf_calls == ["row-c1"]
    # c2 has no GBP → silently ignored (not "skipped"); c3 has a GBP but no match → skipped.
    assert {s["name"] for s in result["skipped"]} == {"Ghost"}


def test_onboard_skips_already_registered_and_no_locations(monkeypatch):
    # Already-registered client is not re-onboarded.
    monkeypatch.setattr(svc, "resolve_connected_locations",
                        lambda: {"locations": [{"location_id": "locations/1", "account_id": "a", "place_id": "P",
                                                "title": "X", "maps_uri": None, "lat": None, "lng": None}], "detail": None})
    clients = [{"id": "c1", "name": "X", "gbp": {"business_name": "X"}, "gbp_place_id": "P"}]
    monkeypatch.setattr(svc, "get_supabase", lambda: _Supa(clients, [{"client_id": "c1", "location_id": "locations/1"}]))
    monkeypatch.setattr(svc, "register_location", lambda *a, **k: {"id": "row"})
    monkeypatch.setattr(svc, "_enqueue_backfill", lambda supabase, rid: None)
    result = svc.onboard_eligible_clients()
    assert result["onboarded"] == [] and result["skipped"] == []

    # No managed listings visible → nothing onboarded, detail surfaced.
    monkeypatch.setattr(svc, "resolve_connected_locations", lambda: {"locations": [], "detail": "gbp_not_connected"})
    result2 = svc.onboard_eligible_clients()
    assert result2["resolved"] == 0 and result2["detail"] == "gbp_not_connected"
