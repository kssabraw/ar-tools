"""Unit tests for the Social P3 (Manager) layer: cadence decisions, the schedule
sweep's per-slot routing, post cancel/reschedule/edit guards, the approval-queue
batch + cadence-queue enroll, and the policy write path. Pure helpers + DB-mocked
guards (no network)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from config import settings
from services.social import fanout, policy, publish, schedules


# ── a tiny fake Supabase query (records updates/inserts; returns canned rows) ──

class _Q:
    def __init__(self, store, tbl):
        self.store = store
        self.tbl = tbl
        self._op = None
        self._fields = None

    def update(self, fields):
        self._op = "update"
        self._fields = fields
        self.store.setdefault("updates", []).append((self.tbl, fields))
        return self

    def insert(self, fields):
        self.store.setdefault("inserts", []).append((self.tbl, fields))
        self._op = "insert"
        self._fields = fields
        return self

    def upsert(self, fields, **k):
        self.store.setdefault("upserts", []).append((self.tbl, fields))
        return self

    def delete(self):
        self.store.setdefault("deletes", []).append(self.tbl)
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        rows = self.store.get("rows", {}).get(self.tbl, [])
        # an update/insert returns the written row echoed (mimics supabase)
        if self._op in ("update", "insert") and not rows:
            rows = [dict(self._fields or {})]
        return SimpleNamespace(data=rows)


def _fake_sb(store):
    return SimpleNamespace(table=lambda t: _Q(store, t))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)


# ── decide_slot (pure) ────────────────────────────────────────────────────────

def test_decide_slot_matrix():
    # all three gates hold + a queued draft → drip
    assert schedules.decide_slot(True, True, True, True) == "drip"
    # auto_fill + gate + account but empty queue → empty-nudge
    assert schedules.decide_slot(True, True, True, False) == "empty"
    # global gate off → suggest (even with everything else)
    assert schedules.decide_slot(True, False, True, True) == "suggest"
    # auto_fill off → suggest
    assert schedules.decide_slot(False, True, True, True) == "suggest"
    # no target account → suggest (can't drip without one)
    assert schedules.decide_slot(True, True, False, True) == "suggest"


# ── resolve_next_run (delegates to the DST-correct GBP helper) ────────────────

def test_resolve_next_run_weekly_future_and_disabled():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    nxt = schedules.resolve_next_run(now, "weekly", 0, None, 9, None)  # next Monday 09:00 UTC
    assert nxt is not None and nxt > now
    assert schedules.resolve_next_run(now, "disabled", None, None, 9, None) is None


# ── _fire_slot routing (drip / empty / suggest) ───────────────────────────────

def _fake_notif():
    calls: list[dict] = []
    return SimpleNamespace(
        emit=lambda cid, kind, title, **k: calls.append({"kind": kind, **k}), calls=calls
    )


def test_fire_slot_drip_publishes_queued_draft(monkeypatch):
    monkeypatch.setattr(settings, "social_auto_publish_enabled", True)
    published: list = []
    fake_fanout = SimpleNamespace(
        next_queued_draft=lambda c, p: {"id": "d1"},
        publish_existing_draft=lambda did, acct: published.append((did, acct)),
    )
    notif = _fake_notif()
    sched = {"platform": "instagram", "account_id": "acct-1", "auto_fill": True}
    schedules._fire_slot("c1", sched, datetime.now(timezone.utc), notif, fake_fanout)
    assert published == [("d1", "acct-1")]
    assert notif.calls[0]["kind"] == "social_slot_published"


def test_fire_slot_empty_queue_nudges(monkeypatch):
    monkeypatch.setattr(settings, "social_auto_publish_enabled", True)
    fake_fanout = SimpleNamespace(
        next_queued_draft=lambda c, p: None,
        publish_existing_draft=lambda *a: pytest.fail("must not publish with empty queue"),
    )
    notif = _fake_notif()
    sched = {"platform": "facebook", "account_id": "acct-1", "auto_fill": True}
    schedules._fire_slot("c1", sched, datetime.now(timezone.utc), notif, fake_fanout)
    assert notif.calls[0]["kind"] == "social_slot_empty"


def test_fire_slot_suggest_when_gate_off(monkeypatch):
    monkeypatch.setattr(settings, "social_auto_publish_enabled", False)  # global gate OFF
    fake_fanout = SimpleNamespace(
        next_queued_draft=lambda c, p: pytest.fail("must not look for a draft when gated off"),
        publish_existing_draft=lambda *a: pytest.fail("must not publish when gated off"),
    )
    notif = _fake_notif()
    sched = {"platform": "instagram", "account_id": "acct-1", "auto_fill": True}
    schedules._fire_slot("c1", sched, datetime.now(timezone.utc), notif, fake_fanout)
    assert notif.calls[0]["kind"] == "social_slot_due"


# ── cancel / reschedule / edit guards ─────────────────────────────────────────

def test_cancel_post_scheduled_ok(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "client_id": "c1", "status": "scheduled"})
    monkeypatch.setattr(publish, "_has_active_publish_job", lambda c, p: False)
    monkeypatch.setattr(publish, "_sb", lambda: _fake_sb(store))
    publish.cancel_post("p1")
    assert ("social_posts", {"status": "cancelled", "status_detail": None, "updated_at": "now()"}) in store["updates"]


def test_cancel_post_wrong_status_409(monkeypatch):
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "client_id": "c1", "status": "published"})
    with pytest.raises(HTTPException) as e:
        publish.cancel_post("p1")
    assert e.value.status_code == 409 and e.value.detail == "social_post_not_cancellable"


def test_cancel_post_publishing_409(monkeypatch):
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "client_id": "c1", "status": "scheduled"})
    monkeypatch.setattr(publish, "_has_active_publish_job", lambda c, p: True)
    with pytest.raises(HTTPException) as e:
        publish.cancel_post("p1")
    assert e.value.detail == "social_post_publishing"


def test_reschedule_past_422(monkeypatch):
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "client_id": "c1", "status": "scheduled"})
    monkeypatch.setattr(publish, "_has_active_publish_job", lambda c, p: False)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    with pytest.raises(HTTPException) as e:
        publish.reschedule_post("p1", past)
    assert e.value.detail == "scheduled_in_past"


def test_reschedule_future_ok(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "client_id": "c1", "status": "scheduled"})
    monkeypatch.setattr(publish, "_has_active_publish_job", lambda c, p: False)
    monkeypatch.setattr(publish, "_sb", lambda: _fake_sb(store))
    future = datetime.now(timezone.utc) + timedelta(days=1)
    publish.reschedule_post("p1", future)
    assert any(t == "social_posts" and "scheduled_at" in f for t, f in store["updates"])


def test_edit_scheduled_post_requires_draft(monkeypatch):
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "status": "scheduled", "draft_id": None})
    with pytest.raises(HTTPException) as e:
        publish.edit_scheduled_post("p1", copy="hi")
    assert e.value.detail == "social_post_no_draft"


def test_edit_scheduled_post_routes_to_draft(monkeypatch):
    seen: list = []
    monkeypatch.setattr(publish, "get_post", lambda pid: {"id": pid, "status": "scheduled", "draft_id": "d1"})
    monkeypatch.setattr(fanout, "update_draft", lambda did, **k: seen.append((did, k)))
    publish.edit_scheduled_post("p1", copy="new", image_urls=["u"])
    assert seen == [("d1", {"copy": "new", "image_urls": ["u"]})]


# ── approval queue: enroll / batch ────────────────────────────────────────────

def test_enqueue_draft_only_from_ready(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(fanout, "get_draft", lambda did: {"id": did, "status": "needs_image"})
    with pytest.raises(HTTPException) as e:
        fanout.enqueue_draft("d1")
    assert e.value.detail == "social_draft_not_queueable"

    monkeypatch.setattr(fanout, "get_draft", lambda did: {"id": did, "status": "ready"})
    monkeypatch.setattr(fanout, "_sb", lambda: _fake_sb(store))
    fanout.enqueue_draft("d1")
    assert ("social_drafts", {"status": "queued", "updated_at": "now()"}) in store["updates"]


def test_dequeue_draft_only_from_queued(monkeypatch):
    monkeypatch.setattr(fanout, "get_draft", lambda did: {"id": did, "status": "ready"})
    with pytest.raises(HTTPException) as e:
        fanout.dequeue_draft("d1")
    assert e.value.detail == "social_draft_not_queued"


def _queued_ig_draft():
    return {"id": "d1", "status": "queued", "platform": "instagram", "format": "feed",
            "media": [{"type": "image", "url": "u"}], "image_urls": ["u"], "platform_metadata": None}


def test_edit_valid_queued_draft_stays_queued(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(fanout, "get_draft", lambda did: _queued_ig_draft())
    monkeypatch.setattr(publish, "_platform_spec", lambda p: {"requires_image": True})
    monkeypatch.setattr(fanout, "_sb", lambda: _fake_sb(store))
    fanout.update_draft("d1", copy="edited")  # media untouched → still valid
    status = [f["status"] for t, f in store["updates"] if "status" in f]
    assert status == ["queued"]


def test_edit_queued_draft_removing_image_leaves_queue(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(fanout, "get_draft", lambda did: _queued_ig_draft())
    monkeypatch.setattr(publish, "_platform_spec", lambda p: {"requires_image": True})
    monkeypatch.setattr(fanout, "_sb", lambda: _fake_sb(store))
    fanout.update_draft("d1", image_urls=[])  # removes the required image → invalid
    status = [f["status"] for t, f in store["updates"] if "status" in f]
    assert status == ["needs_image"]


def test_publish_drafts_batch_partial_success(monkeypatch):
    monkeypatch.setattr(fanout, "get_draft", lambda did: {"id": did, "client_id": "c1"})

    def _pub(did, acct, sched):
        if did == "bad":
            raise HTTPException(status_code=422, detail="social_spec_violation:media_required")
        return {"id": f"post-{did}"}

    monkeypatch.setattr(fanout, "publish_existing_draft", _pub)
    items = [
        SimpleNamespace(draft_id="ok1", account_id="a", scheduled_at=None),
        SimpleNamespace(draft_id="bad", account_id="a", scheduled_at=None),
    ]
    res = fanout.publish_drafts_batch("c1", items)
    assert res[0] == {"draft_id": "ok1", "ok": True, "post_id": "post-ok1", "error": None}
    assert res[1]["ok"] is False and "media_required" in res[1]["error"]


def test_publish_drafts_batch_wrong_client(monkeypatch):
    monkeypatch.setattr(fanout, "get_draft", lambda did: {"id": did, "client_id": "OTHER"})
    monkeypatch.setattr(fanout, "publish_existing_draft",
                        lambda *a: pytest.fail("must not publish another client's draft"))
    res = fanout.publish_drafts_batch("c1", [SimpleNamespace(draft_id="x", account_id="a", scheduled_at=None)])
    assert res[0]["ok"] is False and res[0]["error"] == "social_draft_wrong_client"


# ── policy write path (consumer fields only) ──────────────────────────────────

def test_upsert_policy_filters_and_validates_ceiling(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb(store))
    # a non-positive ceiling is rejected
    with pytest.raises(HTTPException) as e:
        policy.upsert_policy("c1", {"monthly_ceiling_usd": 0})
    assert e.value.detail == "social_ceiling_must_be_positive"

    # non-editable keys are dropped; editable ones are upserted
    policy.upsert_policy("c1", {"autonomy_tier": 3, "image_prompt_template": "brand look"})
    up = store["upserts"][-1][1]
    assert up["image_prompt_template"] == "brand look"
    assert "autonomy_tier" not in up
    assert up["client_id"] == "c1"


def test_upsert_schedule_rejects_out_of_range(monkeypatch):
    monkeypatch.setattr(schedules, "_sb", lambda: _fake_sb({}))
    monkeypatch.setattr(schedules.gbp_timezone, "resolve_client_timezone", lambda c: "UTC")
    # hour ≥ 24 (would ValueError inside compute_next_run_at → 500)
    with pytest.raises(HTTPException) as e:
        schedules.upsert_schedule("c1", {"platform": "instagram", "cadence": "weekly", "hour_local": 25}, None)
    assert e.value.status_code == 422 and e.value.detail == "social_schedule_invalid_hour"
    # day_of_month ≥ 29 (would poison the sweep in a 30-day month)
    with pytest.raises(HTTPException) as e:
        schedules.upsert_schedule("c1", {"platform": "instagram", "cadence": "monthly", "day_of_month": 31}, None)
    assert e.value.detail == "social_schedule_invalid_day"
    # day_of_week > 6
    with pytest.raises(HTTPException) as e:
        schedules.upsert_schedule("c1", {"platform": "instagram", "cadence": "weekly", "day_of_week": 7}, None)
    assert e.value.detail == "social_schedule_invalid_day"


def test_upsert_schedule_valid_persists(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(schedules, "_sb", lambda: _fake_sb(store))
    monkeypatch.setattr(schedules.gbp_timezone, "resolve_client_timezone", lambda c: "UTC")
    schedules.upsert_schedule("c1", {"platform": "Instagram", "cadence": "monthly", "day_of_month": 28, "hour_local": 9}, "u1")
    up = store["upserts"][-1][1]
    assert up["platform"] == "instagram" and up["day_of_month"] == 28 and up["next_run_at"]


def test_list_calendar_naive_bounds_dont_crash(monkeypatch):
    rows = [
        {"id": "a", "scheduled_at": "2026-09-20T09:00:00+00:00", "published_at": None, "created_at": "2026-09-18T00:00:00+00:00"},
        {"id": "b", "scheduled_at": None, "published_at": "2026-09-10T00:00:00+00:00", "created_at": "2026-09-10T00:00:00+00:00"},
    ]
    monkeypatch.setattr(publish, "_sb", lambda: _fake_sb({"rows": {"social_posts": rows}}))
    # naive bounds (a datetime-local query with no tz) must not raise TypeError
    frm = datetime(2026, 9, 19, 0, 0)   # naive
    to = datetime(2026, 9, 21, 0, 0)    # naive
    out = publish.list_calendar("c1", frm, to)
    assert [r["id"] for r in out] == ["a"]   # 'a' scheduled in window; 'b' published before it


def test_get_policy_defaults(monkeypatch):
    monkeypatch.setattr(settings, "social_monthly_ceiling_default_usd", 100.0)
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb({"rows": {"social_policy": []}}))
    out = policy.get_policy("c1")
    assert out["effective_ceiling_usd"] == 100.0
    assert out["default_ceiling_usd"] == 100.0
    assert out["monthly_ceiling_usd"] is None
