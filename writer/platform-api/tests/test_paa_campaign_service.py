"""Impure-layer tests for PAA → SEO Neo Phase 3 (services/paa_campaign_service.py)
— the sweep's state transitions driven through ``_advance`` with the DB / scan
reads / notifications mocked. Verifies the automated gate branches (moved / drill /
HALT / no_data), the settle + rinse clocks, and the Maps-keyword auto-add. No
network / no DB (per the repo's mocking conventions)."""

from datetime import datetime, timedelta, timezone

import pytest

from services import paa_campaign, paa_campaign_service as svc


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _campaign(**over):
    base = {
        "id": "camp1", "set_id": "set1", "client_id": "c1",
        "service_keyword": "metal roof repair", "location": "Denver, CO",
        "state": "content", "drill_level": 0, "settle_until": None,
        "next_action_at": None, "baseline_rank": None, "current_rank": None,
        "history": [],
    }
    base.update(over)
    return base


@pytest.fixture
def applied(monkeypatch):
    """Record every _apply transition; silence notifications + manifest refresh."""
    calls = []

    def fake_apply(cid, updates, *, from_state, to_state, note=None):
        calls.append({"to": to_state, "from": from_state, "updates": updates, "note": note})

    monkeypatch.setattr(svc, "_apply", fake_apply)
    monkeypatch.setattr(svc, "_notify", lambda *a, **k: None)
    # _on_moved refreshes the manifest — stub it out.
    import services.paa_manifest_service as pms
    monkeypatch.setattr(pms, "build_manifest", lambda *a, **k: None)
    return calls


# ── content → settling ────────────────────────────────────────────────────────


def test_content_settles_when_all_posts_ready(applied, monkeypatch):
    monkeypatch.setattr(svc, "_content_ready", lambda set_id, level: True)
    svc._advance(_campaign(state="content"), NOW, _stats())
    assert applied[-1]["to"] == "settling"
    assert applied[-1]["updates"]["settle_until"]  # a settle window was set


def test_content_waits_when_posts_not_ready(applied, monkeypatch):
    monkeypatch.setattr(svc, "_content_ready", lambda set_id, level: False)
    svc._advance(_campaign(state="content"), NOW, _stats())
    assert applied == []  # no transition


# ── settling → scan_ready ─────────────────────────────────────────────────────


def test_settling_becomes_scan_ready_when_elapsed(applied):
    c = _campaign(state="settling", settle_until=(NOW - timedelta(hours=1)).isoformat())
    svc._advance(c, NOW, _stats())
    assert applied[-1]["to"] == "scan_ready"


def test_settling_waits_until_elapsed(applied):
    c = _campaign(state="settling", settle_until=(NOW + timedelta(days=2)).isoformat())
    svc._advance(c, NOW, _stats())
    assert applied == []


# ── scanning → the gate branches ──────────────────────────────────────────────


def _drive_scan(monkeypatch, applied, *, scan, campaign):
    """Run the scanning branch: patch the scan read + the evaluating-refresh."""
    monkeypatch.setattr(svc, "_latest_scan_result", lambda *a, **k: scan)
    # After the first _apply (→ evaluating), _advance refreshes via _campaign.
    monkeypatch.setattr(svc, "_campaign", lambda cid: dict(campaign, state="evaluating"))
    svc._advance(campaign, NOW, _stats())


def test_scan_moved(applied, monkeypatch):
    c = _campaign(state="scanning", baseline_rank=8.0, drill_level=0,
                  scan_requested_at=(NOW - timedelta(days=1)).isoformat())
    _drive_scan(monkeypatch, applied, scan={"scan_id": "s1", "average_rank": 5.0,
                                            "top3_pins": 3}, campaign=c)
    tos = [a["to"] for a in applied]
    assert "evaluating" in tos and tos[-1] == "maintenance"  # moved → maintenance


def test_scan_no_movement_drills(applied, monkeypatch):
    c = _campaign(state="scanning", baseline_rank=6.0, drill_level=0,
                  scan_requested_at=NOW.isoformat())
    _drive_scan(monkeypatch, applied, scan={"scan_id": "s1", "average_rank": 6.0,
                                            "top3_pins": 1}, campaign=c)
    assert applied[-1]["to"] == "drill_ready"


def test_scan_no_movement_at_cap_halts(applied, monkeypatch):
    c = _campaign(state="scanning", baseline_rank=6.0, drill_level=4,
                  scan_requested_at=NOW.isoformat())
    # strategist escalation import is best-effort — force it to no-op via env gate.
    _drive_scan(monkeypatch, applied, scan={"scan_id": "s1", "average_rank": 6.0,
                                            "top3_pins": 1}, campaign=c)
    assert applied[-1]["to"] == "halted"


def test_scan_no_baseline_adopts_and_resettles(applied, monkeypatch):
    c = _campaign(state="scanning", baseline_rank=None, drill_level=0,
                  scan_requested_at=NOW.isoformat())
    _drive_scan(monkeypatch, applied, scan={"scan_id": "s1", "average_rank": 7.0,
                                            "top3_pins": 2}, campaign=c)
    last = applied[-1]
    assert last["to"] == "settling"
    assert last["updates"]["baseline_rank"] == 7.0  # this scan set the baseline


def test_scanning_waits_when_no_scan_yet(applied, monkeypatch):
    monkeypatch.setattr(svc, "_latest_scan_result", lambda *a, **k: None)
    svc._advance(_campaign(state="scanning"), NOW, _stats())
    assert applied == []


# ── maintenance rinse loop ────────────────────────────────────────────────────


def test_maintenance_rechecks_when_due(applied, monkeypatch):
    monkeypatch.setattr(svc, "_latest_scan_result",
                        lambda *a, **k: {"average_rank": 4.0, "top3_pins": 4})
    c = _campaign(state="maintenance", current_rank=4.0,
                  next_action_at=(NOW - timedelta(hours=1)).isoformat())
    svc._advance(c, NOW, _stats())
    assert applied[-1]["to"] == "maintenance"
    assert applied[-1]["updates"]["next_action_at"]  # clock re-armed


def test_maintenance_waits_until_due(applied):
    c = _campaign(state="maintenance",
                  next_action_at=(NOW + timedelta(days=10)).isoformat())
    svc._advance(c, NOW, _stats())
    assert applied == []


# ── sweep gating ──────────────────────────────────────────────────────────────


def test_sweep_noops_when_disabled(monkeypatch):
    monkeypatch.setattr(svc.settings, "paa_campaign_enabled", False)
    stats = svc.run_paa_campaign_sync()
    assert stats == {"settled": 0, "evaluated": 0, "moved": 0, "drilled": 0,
                     "halted": 0, "maintenance": 0}


# ── Maps-keyword auto-add ─────────────────────────────────────────────────────


def test_ensure_tracked_keyword_upserts(monkeypatch):
    recorded = {}

    class _Chain:
        def table(self, name):
            recorded["table"] = name
            return self

        def upsert(self, row, on_conflict=None, ignore_duplicates=None):
            recorded["row"] = row
            recorded["on_conflict"] = on_conflict
            recorded["ignore_duplicates"] = ignore_duplicates
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    monkeypatch.setattr(svc, "_sb", lambda: _Chain())
    svc._ensure_tracked_keyword("c1", "metal roof repair")
    assert recorded["table"] == "maps_keywords"
    assert recorded["row"] == {"client_id": "c1", "keyword": "metal roof repair",
                               "active": True}
    assert recorded["on_conflict"] == "client_id,keyword"
    assert recorded["ignore_duplicates"] is True


def _stats():
    return {"settled": 0, "evaluated": 0, "moved": 0, "drilled": 0,
            "halted": 0, "maintenance": 0}
