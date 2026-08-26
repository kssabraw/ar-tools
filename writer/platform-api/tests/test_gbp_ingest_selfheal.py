"""A successful GBP ingest self-heals a stale ``no_access`` back to ``ok``.

A transient 403/404 flips a location to ``no_access``; the scheduled sync then
skips it (it only ingests ``ok`` locations), so without this a location stays
sidelined — hidden from the dashboard — until a human re-verifies. A successful
manual re-sync is live proof of access and must clear the flag.

The Supabase client + the Google fetch are stubbed; only the DB write payload is
asserted.
"""

from __future__ import annotations

import types

from services import gbp_metrics_ingest as ing


class _Chain:
    """Fluent Supabase query stub: methods return self; ``execute`` returns the
    found location only for the initial SELECT, and records ``update`` payloads."""

    def __init__(self, table: str, loc_row: dict, captured: list[dict]):
        self.table = table
        self.loc_row = loc_row
        self.captured = captured
        self._is_update = False

    def select(self, *a, **k):
        return self

    def insert(self, *a, **k):
        return self

    def upsert(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self._is_update = True
        if self.table == "gbp_locations":
            self.captured.append(payload)
        return self

    def execute(self):
        data = [self.loc_row] if (self.table == "gbp_locations" and not self._is_update) else []
        return types.SimpleNamespace(data=data)


class _Supabase:
    def __init__(self, loc_row: dict, captured: list[dict]):
        self.loc_row = loc_row
        self.captured = captured

    def table(self, name: str):
        return _Chain(name, self.loc_row, self.captured)


def test_successful_ingest_self_heals_access_status(monkeypatch):
    loc = {"id": "loc-1", "location_id": "locations/123", "access_status": "no_access"}
    captured: list[dict] = []

    monkeypatch.setattr(ing.settings, "gbp_metrics_enabled", True)
    monkeypatch.setattr(ing, "get_supabase", lambda: _Supabase(loc, captured))
    monkeypatch.setattr(ing.gbp, "normalize_location_id", lambda x: x)
    monkeypatch.setattr(
        ing.gbp,
        "fetch_daily_metrics",
        lambda *a, **k: [{"metric": "CALL_CLICKS", "date": "2026-08-01", "value": 3}],
    )

    result = ing.ingest_location("loc-1", "2026-07-01", "2026-08-01")

    assert result.status == "ok"
    assert result.rows == 1
    assert captured, "expected a gbp_locations update on success"
    assert captured[-1].get("access_status") == "ok"
    assert "last_synced_at" in captured[-1]
