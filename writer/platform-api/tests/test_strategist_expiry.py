"""Unit tests for services/strategist_expiry.py + the audit 'expired' bucket."""
from datetime import datetime, timezone

from services import sermastr_audit, strategist_expiry
from config import settings


# ---------------------------------------------------------------------------
# Pure marker
# ---------------------------------------------------------------------------
def test_mark_expired_only_touches_proposed():
    props = [
        {"title": "a", "status": "proposed"},
        {"title": "b", "status": "approved"},
        {"title": "c", "status": "dismissed"},
        {"title": "d", "status": "superseded"},
        {"title": "e"},  # missing status defaults to 'proposed'
    ]
    out, changed = strategist_expiry.mark_expired(props)
    assert changed == [0, 4]
    assert out[0]["status"] == "expired"
    assert out[4]["status"] == "expired"
    # untouched
    assert [out[i]["status"] for i in (1, 2, 3)] == ["approved", "dismissed", "superseded"]
    # pure — input not mutated
    assert props[0]["status"] == "proposed"
    # nothing to do
    assert strategist_expiry.mark_expired([{"status": "approved"}]) == ([{"status": "approved"}], [])
    assert strategist_expiry.mark_expired([]) == ([], [])


# ---------------------------------------------------------------------------
# Sweep (fake Supabase)
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, data): self.data = data


class _Query:
    """Minimal query builder: records update payloads keyed by the eq() id;
    returns canned select rows for its table."""
    def __init__(self, table, store):
        self.table, self.store = table, store
        self._update = None
        self._eq_id = None

    def select(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def in_(self, *a, **k): return self

    def eq(self, _col, val):
        self._eq_id = val
        return self

    def update(self, payload):
        self._update = payload
        return self

    def execute(self):
        if self._update is not None:
            self.store["updates"].append({self._eq_id: self._update})
            return _Result([{"id": self._eq_id}])
        return _Result(self.store["rows"].get(self.table, []))


def _sweep_env(monkeypatch, rows):
    store = {"rows": {"strategy_reviews": rows, "clients": []}, "updates": []}
    monkeypatch.setattr(strategist_expiry, "get_supabase",
                        lambda: type("SB", (), {"table": lambda _self, n: _Query(n, store)})())
    calls = []
    monkeypatch.setattr(sermastr_audit, "record_expired", lambda **kw: calls.append(kw))
    return store, calls


def test_expire_stale_proposals_expires_and_audits(monkeypatch):
    monkeypatch.setattr(settings, "strategist_proposal_expiry_enabled", True)
    monkeypatch.setattr(settings, "strategist_proposal_expiry_days", 30)
    rows = [
        {"id": "r1", "client_id": "c1", "trigger": "scheduled",
         "proposals": [{"title": "x", "status": "proposed"},
                       {"title": "y", "status": "approved"}]},
        {"id": "r2", "client_id": "c2", "trigger": "escalation",
         "proposals": [{"title": "z", "status": "dismissed"}]},  # nothing to expire
    ]
    store, calls = _sweep_env(monkeypatch, rows)
    n = strategist_expiry.expire_stale_proposals(now=datetime(2026, 9, 17, tzinfo=timezone.utc))
    assert n == 1
    # only r1 was written, with the proposed proposal flipped to expired
    assert store["updates"] == [{"r1": {"proposals": [
        {"title": "x", "status": "expired"}, {"title": "y", "status": "approved"}]}}]
    # one audit row for the expired proposal
    assert len(calls) == 1
    assert calls[0]["review_id"] == "r1" and calls[0]["idx"] == 0


def test_expire_disabled_or_zero_window_noop(monkeypatch):
    rows = [{"id": "r1", "client_id": "c1", "trigger": "scheduled",
             "proposals": [{"status": "proposed"}]}]
    store, calls = _sweep_env(monkeypatch, rows)
    monkeypatch.setattr(settings, "strategist_proposal_expiry_enabled", False)
    monkeypatch.setattr(settings, "strategist_proposal_expiry_days", 30)
    assert strategist_expiry.expire_stale_proposals() == 0
    monkeypatch.setattr(settings, "strategist_proposal_expiry_enabled", True)
    monkeypatch.setattr(settings, "strategist_proposal_expiry_days", 0)
    assert strategist_expiry.expire_stale_proposals() == 0
    assert store["updates"] == [] and calls == []


# ---------------------------------------------------------------------------
# Audit: 'expired' is its own bucket, excluded from decided/dismiss_rate
# ---------------------------------------------------------------------------
def test_audit_expired_excluded_from_rates():
    rows = [
        {"decision": "approved", "proposal_kind": "k"},
        {"decision": "dismissed", "proposal_kind": "k"},
        {"decision": "expired", "proposal_kind": "k"},
        {"decision": "superseded", "proposal_kind": "k"},
    ]
    stats = sermastr_audit.decision_stats(rows)
    o = stats["overall"]
    assert o["expired"] == 1 and o["superseded"] == 1
    assert o["approved"] == 1 and o["dismissed"] == 1
    sig = sermastr_audit.learning_signals(rows)["by_kind"]["k"]
    # dismiss_rate is over DECIDED (approved+dismissed) only — expired doesn't dilute it
    assert sig["dismiss_rate"] == 0.5
