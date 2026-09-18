"""Unit tests for the GSC connection-health watch (services/gsc_health.py).

Pure helpers (episode key, digest copy/severity) plus the sweep's three paths —
self-heal on recovery, alert while denied, and the disabled/unconfigured skips —
with Supabase, the Google verify, the back-fill enqueue and notifications stubbed.
Nothing hits the network or a DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from services import gsc_health


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_access_episode_key_stable_within_week_changes_across_weeks():
    a = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)  # Wed
    b = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)  # Fri, same ISO week
    c = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)  # next week
    assert gsc_health.access_episode_key("p1", a) == gsc_health.access_episode_key("p1", b)
    assert gsc_health.access_episode_key("p1", a) != gsc_health.access_episode_key("p1", c)
    assert gsc_health.access_episode_key("p1", a) != gsc_health.access_episode_key("p2", a)


def test_build_access_digest_warning_vs_critical_and_email():
    warn = gsc_health.build_access_digest("Acme", "https://acme.com/", "svc@proj.iam", 13, 14)
    assert warn["severity"] == "warning"
    assert "svc@proj.iam" in warn["summary"]
    assert "https://acme.com/" in warn["summary"]
    assert "13 days" in warn["summary"]

    crit = gsc_health.build_access_digest("Acme", "https://acme.com/", "svc@proj.iam", 20, 14)
    assert crit["severity"] == "critical"


def test_build_access_digest_missing_email_and_days_falls_back():
    d = gsc_health.build_access_digest("Acme", "https://acme.com/", None, None, 14)
    assert d["severity"] == "warning"
    assert "Rankings → Settings" in d["summary"]  # generic email fallback
    assert "stopped updating" in d["summary"]     # generic frozen clause


# ---------------------------------------------------------------------------
# Sweep fakes
# ---------------------------------------------------------------------------
class _Chain:
    def __init__(self, table, store):
        self.table_name = table
        self.store = store
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, *a, **k):
        self._op = "insert"
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "update":
            self.store["updates"].append((self.table_name, self._payload))
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=list(self.store["data"].get(self.table_name, [])))


class _Supabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Chain(name, self.store)


def _wire(monkeypatch, store, verify_status, *, enabled=True, has_key=True):
    monkeypatch.setattr(gsc_health.settings, "gsc_access_monitor_enabled", enabled)
    monkeypatch.setattr(gsc_health.settings, "gsc_access_critical_days", 14)
    monkeypatch.setattr(
        gsc_health.settings, "google_service_account_key", "{}" if has_key else ""
    )
    monkeypatch.setattr(gsc_health, "get_supabase", lambda: _Supabase(store))
    monkeypatch.setattr(
        gsc_health.gsc_service, "get_service_account_email", lambda: "svc@proj.iam"
    )
    monkeypatch.setattr(
        gsc_health.gsc_service,
        "verify_property_access",
        lambda site_url, ptype: SimpleNamespace(status=verify_status, detail=None),
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        gsc_health.notifications,
        "emit",
        lambda **kw: emitted.append(kw) or "nid",
    )
    enqueued: list[str] = []
    import services.gsc_ingest as gi

    monkeypatch.setattr(gi, "enqueue_ingest", lambda pid: enqueued.append(pid) or "job")
    return emitted, enqueued


def _store(props, *, data_date="2026-09-05"):
    return {
        "data": {
            "gsc_properties": props,
            "clients": [{"id": "c1", "name": "Acme"}],
            "gsc_query_daily": [{"date": data_date}],
        },
        "updates": [],
    }


_PROP = {
    "id": "prop-1",
    "client_id": "c1",
    "site_url": "https://acme.com/",
    "property_type": "url_prefix",
    "access_status": "no_access",
}


# ---------------------------------------------------------------------------
# Sweep behaviour
# ---------------------------------------------------------------------------
def test_sweep_skips_when_disabled(monkeypatch):
    emitted, _ = _wire(monkeypatch, _store([_PROP]), "no_access", enabled=False)
    assert gsc_health.run_gsc_access_sweep() == {"skipped": "disabled"}
    assert emitted == []


def test_sweep_skips_without_service_account(monkeypatch):
    emitted, _ = _wire(monkeypatch, _store([_PROP]), "no_access", has_key=False)
    assert gsc_health.run_gsc_access_sweep() == {"skipped": "no_service_account"}
    assert emitted == []


def test_sweep_recovers_when_access_returns(monkeypatch):
    store = _store([_PROP])
    emitted, enqueued = _wire(monkeypatch, store, "ok")

    result = gsc_health.run_gsc_access_sweep()

    assert result == {"checked": 1, "recovered": 1, "alerted": 0}
    # Flipped back to ok...
    assert store["updates"], "expected a gsc_properties update on recovery"
    tbl, payload = store["updates"][-1]
    assert tbl == "gsc_properties" and payload["access_status"] == "ok"
    assert "last_verified_at" in payload
    # ...queued an immediate back-fill...
    assert enqueued == ["prop-1"]
    # ...and posted a recovery note.
    assert len(emitted) == 1
    assert emitted[0]["kind"] == "gsc_access"
    assert emitted[0]["severity"] == "info"
    assert emitted[0]["payload"]["state"] == "recovered"


def test_sweep_alerts_when_still_denied(monkeypatch):
    store = _store([_PROP], data_date="2026-08-20")  # long-frozen → critical
    emitted, enqueued = _wire(monkeypatch, store, "no_access")
    monkeypatch.setattr(
        gsc_health, "datetime", _fixed_now(datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc))
    )

    result = gsc_health.run_gsc_access_sweep()

    assert result == {"checked": 1, "recovered": 0, "alerted": 1}
    assert not store["updates"], "a still-denied property must not be flipped to ok"
    assert enqueued == []
    assert len(emitted) == 1
    e = emitted[0]
    assert e["kind"] == "gsc_access" and e["client_id"] == "c1"
    assert e["severity"] == "critical"  # frozen since 2026-08-20 → ≥14 days
    assert e["payload"]["state"] == "lost"
    assert "prop-1" in e["dedupe_key"]


def test_sweep_ignores_transient_error_status(monkeypatch):
    store = _store([_PROP])
    emitted, enqueued = _wire(monkeypatch, store, "error")
    result = gsc_health.run_gsc_access_sweep()
    assert result == {"checked": 1, "recovered": 0, "alerted": 0}
    assert store["updates"] == [] and enqueued == [] and emitted == []


def test_sweep_noop_when_no_broken_properties(monkeypatch):
    emitted, _ = _wire(monkeypatch, _store([]), "no_access")
    assert gsc_health.run_gsc_access_sweep() == {"checked": 0, "recovered": 0, "alerted": 0}
    assert emitted == []


class _fixed_now:
    """Stub for gsc_health.datetime so 'days frozen' is deterministic."""

    def __init__(self, now):
        self._now = now

    def now(self, tz=None):
        return self._now
