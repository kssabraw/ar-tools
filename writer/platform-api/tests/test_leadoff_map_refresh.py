"""Wiring tests for the LeadOff map-refresh job (services.leadoff_actions
.run_map_refresh_job): the ~$0.004 Maps-SERP-only pin re-pull. The pure pieces it
reuses (pin parsing, persist row-builder) are covered by test_leadoff_brand /
test_leadoff_gbp_pins; here we pin the job's own control flow — persist only a
non-empty pull, mark complete with the count, fail cleanly when the market is
unknown — with the DB + DataForSEO mocked."""
from unittest.mock import AsyncMock

import services.leadoff_actions as la


class _Chain:
    """Minimal chainable stand-in for a supabase query builder. Every filter/
    select method returns self; execute() returns the configured rows and, when
    given a sink, records the update payload."""
    def __init__(self, rows=None, sink=None):
        self._rows = rows if rows is not None else []
        self._sink = sink
        self._payload = None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def update(self, payload):
        self._payload = payload
        if self._sink is not None:
            self._sink.append(payload)
        return self

    def insert(self, *a, **k): return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


def _fake_ms(board_rows):
    def ms(table):
        if table == "leadoff_board":
            return _Chain(rows=board_rows)
        if table == "cities":
            return _Chain(rows=[{"city_id": 1, "latitude": 34.7, "longitude": -92.3}])
        return _Chain(rows=[])
    return ms


def _fake_supabase(update_sink):
    class _SB:
        def table(self, name):
            return _Chain(sink=update_sink)
    return _SB()


BOARD = [{"city_id": 1, "category_id": "chimney_sweep", "category": "Chimney sweep",
          "city_name": "Little Rock", "state_code": "AR"}]


async def _run(monkeypatch, *, board=BOARD, pins, persist_return=None):
    updates: list[dict] = []
    persisted: dict = {}

    monkeypatch.setattr(la, "_ms", _fake_ms(board))
    monkeypatch.setattr(la, "get_supabase", lambda: _fake_supabase(updates))
    monkeypatch.setattr("services.leadoff_brand.fetch_market_pins",
                        AsyncMock(return_value=pins))

    def _persist(source, city_id, category_id, pin_list):
        persisted.update(source=source, city_id=city_id,
                         category_id=category_id, pins=pin_list)
        return persist_return if persist_return is not None else len(pin_list)
    monkeypatch.setattr("services.leadoff_gbp_pins.persist_gbp_pins", _persist)

    await la.run_map_refresh_job(
        {"id": "job1", "payload": {"city_id": 1, "category_id": "chimney_sweep"}})
    return updates, persisted


class TestRunMapRefreshJob:
    async def test_persists_nonempty_pull_and_completes(self, monkeypatch):
        pins = [{"lat": 34.7, "lng": -92.3, "business_name": "A"},
                {"lat": 34.8, "lng": -92.4, "business_name": "B"}]
        updates, persisted = await _run(monkeypatch, pins=pins)
        # persist called with the fetched pins under the 'scout' source
        assert persisted["source"] == "scout"
        assert persisted["pins"] == pins
        assert persisted["city_id"] == 1 and persisted["category_id"] == "chimney_sweep"
        # job completes with the written count
        assert updates and updates[-1]["status"] == "complete"
        assert updates[-1]["result"] == {"gbp_pins": 2}

    async def test_empty_pull_skips_persist_and_preserves_prior_map(self, monkeypatch):
        # An empty SERP must NOT call persist — its delete-stale step would wipe
        # the market's prior pins. Job still completes, gbp_pins: 0.
        updates, persisted = await _run(monkeypatch, pins=[])
        assert persisted == {}                      # persist never called
        assert updates[-1]["status"] == "complete"
        assert updates[-1]["result"] == {"gbp_pins": 0}

    async def test_unknown_market_fails_cleanly(self, monkeypatch):
        updates, persisted = await _run(monkeypatch, board=[], pins=[])
        assert persisted == {}
        assert updates[-1]["status"] == "failed"
        assert "market_not_found" in updates[-1]["error"]
