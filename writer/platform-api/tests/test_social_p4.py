"""Unit tests for Social P4 (Phase A): the autonomy tier actions in the shared policy
engine + the Social Policy planning-field write path. Pure helpers + a DB-mocked upsert
(no network)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from config import settings
from services import autonomy_policy
from services.social import policy


# ── a tiny fake Supabase (records upserts; returns canned rows) ───────────────

class _Q:
    def __init__(self, store, tbl):
        self.store = store
        self.tbl = tbl

    def upsert(self, fields, **k):
        self.store.setdefault("upserts", []).append((self.tbl, fields))
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=self.store.get("rows", {}).get(self.tbl, []))


def _fake_sb(store):
    return SimpleNamespace(table=lambda t: _Q(store, t))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(settings, "social_autonomy_cap_tier", 2)
    monkeypatch.setattr(settings, "social_autonomy_enabled", False)


# ── the tier ladder (autonomy_policy) ─────────────────────────────────────────

def test_social_actions_registered_at_expected_tiers():
    assert autonomy_policy.ACTION_TIERS["generate_social_drafts"] == 1
    assert autonomy_policy.ACTION_TIERS["queue_social_draft"] == 2
    assert autonomy_policy.ACTION_TIERS["publish_social_post"] == 3
    # generation spends → rate-capped; queue/publish are not "content generation".
    assert "generate_social_drafts" in autonomy_policy.CONTENT_ACTIONS
    assert "queue_social_draft" not in autonomy_policy.CONTENT_ACTIONS


def test_generate_and_queue_ladder():
    gen = {"action": "generate_social_drafts", "cost_usd": 0.1}
    que = {"action": "queue_social_draft"}
    # Tier 1: generate auto-runs; queue (tier 2) must be proposed.
    assert autonomy_policy.classify(gen, client_tier=1, budget_left=5.0).outcome == "auto"
    assert autonomy_policy.classify(que, client_tier=1).outcome == "propose"
    # Tier 2: both auto-run.
    assert autonomy_policy.classify(gen, client_tier=2, budget_left=5.0).outcome == "auto"
    assert autonomy_policy.classify(que, client_tier=2).outcome == "auto"


def test_publish_social_post_never_auto_at_cap():
    # publish is tier 3; the social cap is 2, so it can never auto-run in v1.
    pub = {"action": "publish_social_post"}
    assert autonomy_policy.classify(pub, client_tier=2).outcome == "propose"


def test_generate_blocked_when_over_budget_or_frozen_or_capped():
    gen = {"action": "generate_social_drafts", "cost_usd": 5.0}
    # over budget → propose (advisory pre-filter)
    assert autonomy_policy.classify(gen, client_tier=1, budget_left=1.0).outcome == "propose"
    # frozen → escalate (observation only)
    assert autonomy_policy.classify(gen, client_tier=1, budget_left=99.0, freeze=True).outcome == "escalate"
    # weekly content rate cap reached → propose
    assert autonomy_policy.classify(
        gen, client_tier=1, budget_left=99.0, content_this_week=3, content_cap=3
    ).outcome == "propose"


# ── clean_str_list (pure) ─────────────────────────────────────────────────────

def test_clean_str_list_normalises():
    assert policy.clean_str_list(None) == []
    assert policy.clean_str_list(["  Roofing ", "roofing", "", "Storm Damage"]) == ["Roofing", "Storm Damage"]
    # a newline/comma string (a UI textarea) is split
    assert policy.clean_str_list("a, b\nc") == ["a", "b", "c"]
    # non-list/str → []
    assert policy.clean_str_list(42) == []


def test_clean_str_list_caps_length():
    many = [f"t{i}" for i in range(policy._MAX_LIST_ITEMS + 25)]
    assert len(policy.clean_str_list(many)) == policy._MAX_LIST_ITEMS


# ── the planning-field write path ─────────────────────────────────────────────

def test_upsert_tier_valid_persists(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb(store))
    policy.upsert_policy("c1", {"autonomy_tier": 2, "allowed_topics": ["roofing", "roofing", "storms"]})
    up = store["upserts"][-1][1]
    assert up["autonomy_tier"] == 2
    assert up["allowed_topics"] == ["roofing", "storms"]   # deduped/cleaned


def test_upsert_tier_out_of_range_rejected(monkeypatch):
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb({}))
    with pytest.raises(HTTPException) as e:
        policy.upsert_policy("c1", {"autonomy_tier": 3})   # cap is 2
    assert e.value.status_code == 422 and e.value.detail == "social_autonomy_tier_out_of_range"


def test_upsert_tier_non_int_rejected(monkeypatch):
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb({}))
    with pytest.raises(HTTPException) as e:
        policy.upsert_policy("c1", {"autonomy_tier": "high"})
    assert e.value.detail == "social_autonomy_tier_invalid"


def test_upsert_tier_null_clears_to_off(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb(store))
    policy.upsert_policy("c1", {"autonomy_tier": None})
    assert store["upserts"][-1][1]["autonomy_tier"] == 0


def test_get_policy_returns_planning_fields_and_context(monkeypatch):
    monkeypatch.setattr(settings, "social_autonomy_enabled", True)
    rows = [{
        "monthly_ceiling_usd": None, "autonomy_tier": 5,   # a legacy over-cap value
        "allowed_topics": ["roofing"], "blocked_topics": None,
        "tone_prefs": "warm, expert", "competitor_focus": ["acme"],
    }]
    monkeypatch.setattr(policy, "_sb", lambda: _fake_sb({"rows": {"social_policy": rows}}))
    out = policy.get_policy("c1")
    assert out["autonomy_tier"] == 2          # clamped to the cap on read
    assert out["allowed_topics"] == ["roofing"]
    assert out["blocked_topics"] == []
    assert out["tone_prefs"] == "warm, expert"
    assert out["competitor_focus"] == ["acme"]
    assert out["autonomy_cap_tier"] == 2
    assert out["autonomy_enabled"] is True
