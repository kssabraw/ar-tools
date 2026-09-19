"""Unit tests for Social P4 (Phase D) — the agent integrations:

* ``manager.activity_item`` — the pure ledger-row shaper the activity view reads.
* ``director.seams.social_seams`` + ``compute_flags`` — the two social seam
  predicates and their wiring into the flag assembly.
* ``director.seams.autonomy_proposed_unactioned`` — now carries ``domain``.
* ``director.providers.prov_autonomy`` — domain-aware split.
* ``director.providers.prov_social`` — aging drafts + idle accounts.
* ``task_producers`` — the two PACE social producers' gating + the weekly sweep.

Pure functions + DB-mocked reads (no network), mirroring the module's other tests.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from config import settings
from services import task_producers as TP
from services.director import providers as P
from services.director import seams as S
from services.social import manager

TODAY = date(2026, 9, 19)


# ── a DB-read mock that chains the query builder + routes by table ────────────

def _table_mock(rows):
    mock = MagicMock()
    for m in ("select", "eq", "is_", "in_", "gte", "lt", "order", "limit", "neq"):
        getattr(mock, m).return_value = mock
    mock.execute.return_value = MagicMock(data=rows)
    return mock


def _route_sb(rows_by_table):
    sb = MagicMock()
    sb.table.side_effect = lambda t: _table_mock(rows_by_table.get(t, []))
    return sb


# ── manager.activity_item (pure) ─────────────────────────────────────────────

def test_activity_item_shapes_produced_and_queued():
    row = {
        "id": "r1", "trigger": "scheduled", "tier": 2,
        "goal_snapshot": {"deficits": {"facebook": 2, "instagram": 1}, "auto_queue": True},
        "decisions": [{"action": "generate_social_drafts", "outcome": "auto"}],
        "actions_taken": ["a1", "a2"],
        "cost_usd": 0,
        "created_at": "2026-09-18T10:00:00Z",
    }
    item = manager.activity_item(row)
    assert item["produced"] == 2
    assert item["auto_queued"] is True
    assert item["proposed"] == 0
    assert item["platforms"] == ["facebook", "instagram"]
    assert item["at"] == "2026-09-18T10:00:00Z"
    assert item["tier"] == 2


def test_activity_item_counts_proposed_batches():
    row = {
        "id": "r2", "trigger": "empty_queue", "tier": 1,
        "goal_snapshot": {"deficits": {"x": 1}, "auto_queue": False},
        "decisions": [{"proposed_batches": [["x"], ["facebook"]], "auto_queue": False}],
        "actions_taken": [],
        "cost_usd": 0.05,
        "created_at": "2026-09-18T10:00:00Z",
    }
    item = manager.activity_item(row)
    assert item["produced"] == 0
    assert item["proposed"] == 2
    assert item["auto_queued"] is False


def test_activity_item_tolerates_missing_fields():
    item = manager.activity_item({})
    assert item["produced"] == 0 and item["proposed"] == 0
    assert item["platforms"] == []
    assert item["auto_queued"] is False
    assert item["at"] is None


# ── social seams (pure) ──────────────────────────────────────────────────────

def test_social_seams_aging_fires_at_threshold_silent_below():
    model = {"social": {"aging_drafts": [
        {"client_id": "c1", "draft_id": "d1", "platform": "facebook", "angle": "A", "since": "2026-09-13"},  # 6 days
        {"client_id": "c1", "draft_id": "d2", "platform": "x", "angle": "B", "since": "2026-09-17"},          # 2 days
    ], "idle_accounts": []}}
    flags = S.social_seams(model, TODAY, aging_days=5, idle_days=21)
    assert len(flags) == 1
    f = flags[0]
    assert f["seam"] == "social_draft_aging"
    assert f["client_id"] == "c1"
    assert f["ident"] == "d1"
    assert f["evidence"]["days_ready"] == 6
    assert f["threshold_days"] == 5


def test_social_seams_idle_account_fires():
    model = {"social": {"aging_drafts": [], "idle_accounts": [
        {"client_id": "c2", "platform": "instagram", "last_published_at": "2026-08-01", "since": "2026-08-01"},
        {"client_id": "c2", "platform": "facebook", "last_published_at": "2026-09-15", "since": "2026-09-15"},  # 4 days — fresh
    ]}}
    flags = S.social_seams(model, TODAY, aging_days=5, idle_days=21)
    assert len(flags) == 1
    f = flags[0]
    assert f["seam"] == "social_account_idle"
    assert f["ident"] == "instagram"
    assert f["evidence"]["days_idle"] >= 21


def test_social_seams_empty_and_none_model():
    assert S.social_seams({}, TODAY, 5, 21) == []
    assert S.social_seams({"social": None}, TODAY, 5, 21) == []


def test_compute_flags_social_defaults_off_then_fires_with_thresholds():
    model = {"social": {"aging_drafts": [
        {"client_id": "c1", "draft_id": "d1", "platform": "x", "angle": "A", "since": "2026-01-01"},
    ], "idle_accounts": []}}
    base = {"approved_unplaced_days": 3, "proposal_pending_days": 21,
            "qa_idle_days": 7, "autonomy_unactioned_days": 7}
    # No social thresholds → the default (10_000) suppresses social flags.
    out = S.compute_flags(model, TODAY, base)
    assert all(f["seam"] not in ("social_draft_aging", "social_account_idle") for f in out["flags"])
    # With thresholds → fires.
    out2 = S.compute_flags(model, TODAY, {**base, "social_draft_aging_days": 5, "social_account_idle_days": 21})
    assert any(f["seam"] == "social_draft_aging" for f in out2["flags"])


def test_autonomy_proposed_unactioned_carries_domain():
    model = {"autonomy": {"proposed_unactioned": [
        {"client_id": "c1", "domain": "social", "run_id": "r1",
         "action": "generate_social_drafts", "since": "2026-09-01"},
        {"client_id": "c1", "run_id": "r2", "action": "reoptimize_page", "since": "2026-09-01"},  # legacy, no domain
    ]}}
    flags = S.autonomy_proposed_unactioned(model, TODAY, threshold_days=7)
    assert len(flags) == 2
    assert flags[0]["evidence"]["domain"] == "social"
    assert flags[1]["evidence"]["domain"] == "seo"   # defaulted


# ── prov_autonomy domain split (DB-mocked) ───────────────────────────────────

def test_prov_autonomy_splits_by_domain_and_tags_proposed():
    rows = [
        {"id": "r1", "client_id": "c1", "domain": "seo", "decisions": [
            {"outcome": "auto", "executed": True},
            {"outcome": "propose", "action": "reoptimize_page", "keyword": "roof repair"}],
         "actions_taken": [], "cost_usd": 0, "created_at": "2026-09-18T00:00:00Z"},
        {"id": "r2", "client_id": "c1", "domain": "social", "decisions": [
            {"outcome": "propose", "action": "generate_social_drafts"}],
         "actions_taken": [], "cost_usd": 0, "created_at": "2026-09-18T00:00:00Z"},
    ]
    sb = MagicMock()
    sb.table.return_value = _table_mock(rows)
    out = P.prov_autonomy(sb, ["c1"], TODAY)
    assert out["by_domain"]["seo"] == {"executed": 1, "proposed": 1, "escalated": 0}
    assert out["by_domain"]["social"] == {"executed": 0, "proposed": 1, "escalated": 0}
    assert out["executed"] == 1 and out["proposed"] == 2
    domains = {u["domain"] for u in out["proposed_unactioned"]}
    assert domains == {"seo", "social"}


# ── prov_social (DB-mocked) ──────────────────────────────────────────────────

def test_prov_social_reports_aging_and_latest_idle(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    drafts = [{"id": "d1", "client_id": "c1", "platform": "facebook", "angle": "A", "updated_at": "2026-09-10"}]
    # published rows come back published_at-desc from the query; first per platform wins.
    posts = [
        {"client_id": "c1", "platform": "instagram", "published_at": "2026-08-05"},
        {"client_id": "c1", "platform": "instagram", "published_at": "2026-08-01"},
    ]
    sb = _route_sb({"social_drafts": drafts, "social_posts": posts})
    out = P.prov_social(sb, ["c1"], TODAY)
    assert len(out["aging_drafts"]) == 1
    assert out["aging_drafts"][0]["since"] == "2026-09-10"
    assert len(out["idle_accounts"]) == 1
    assert out["idle_accounts"][0]["last_published_at"] == "2026-08-05"   # newest wins


def test_prov_social_none_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", False)
    assert P.prov_social(MagicMock(), None, TODAY) is None


def test_prov_social_none_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    sb = _route_sb({"social_drafts": [], "social_posts": []})
    assert P.prov_social(sb, ["c1"], TODAY) is None


# ── PACE social producers (gating + weekly sweep) ────────────────────────────

def test_iso_week_ref_stable():
    y, w, _ = date(2026, 9, 19).isocalendar()
    assert TP._iso_week_ref("c1", date(2026, 9, 19)) == f"c1:{y}-W{w:02d}"


def test_run_social_calendar_sweep_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "native_tasks_enabled", True)
    monkeypatch.setattr(settings, "task_producer_social_calendar_enabled", False)
    assert TP.run_social_calendar_sweep(TODAY) == 0


def test_run_social_calendar_sweep_noop_off_weekday(monkeypatch):
    monkeypatch.setattr(settings, "native_tasks_enabled", True)
    monkeypatch.setattr(settings, "task_producer_social_calendar_enabled", True)
    day = date(2026, 9, 21)
    monkeypatch.setattr(settings, "task_producer_social_calendar_weekday", (day.weekday() + 1) % 7)
    assert TP.run_social_calendar_sweep(day) == 0


def test_run_social_calendar_sweep_fires_once_per_distinct_client(monkeypatch):
    monkeypatch.setattr(settings, "native_tasks_enabled", True)
    monkeypatch.setattr(settings, "task_producer_social_calendar_enabled", True)
    day = date(2026, 9, 21)
    monkeypatch.setattr(settings, "task_producer_social_calendar_weekday", day.weekday())
    rows = [{"client_id": "c1"}, {"client_id": "c1"}, {"client_id": "c2"}, {"client_id": None}]
    monkeypatch.setattr(TP, "get_supabase", lambda: _route_sb({"social_post_schedules": rows}))
    called: list[str] = []
    monkeypatch.setattr(TP, "on_social_calendar", lambda cid, today=None: called.append(cid))
    n = TP.run_social_calendar_sweep(day)
    assert n == 2
    assert set(called) == {"c1", "c2"}


def test_on_social_drafts_generated_noop_when_off_or_zero(monkeypatch):
    monkeypatch.setattr(settings, "native_tasks_enabled", True)
    monkeypatch.setattr(settings, "task_producer_social_drafts_review_enabled", False)
    # Flag off → returns cleanly without touching the DB (no _create).
    assert TP.on_social_drafts_generated("c1", 3) is None
    # Flag on but zero count → still a no-op.
    monkeypatch.setattr(settings, "task_producer_social_drafts_review_enabled", True)
    assert TP.on_social_drafts_generated("c1", 0) is None
