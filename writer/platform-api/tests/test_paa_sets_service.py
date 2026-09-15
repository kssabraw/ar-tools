"""Impure-layer tests for PAA → SEO Neo v1 (services/paa_sets_service.py) with
mocks — the writer-constraint ENFORCEMENT: one Blog Writer run per chosen PAA,
each seeded from the exact PAA string with writer_notes carrying the three rules
and an idempotent per-item source_ref; the cannibalization gate blocking a create;
and the deterministic post-generation verification. No network / no DB (per the
repo's mocking conventions)."""

import pytest

from services import paa_sets_service as svc


class _FakeChain:
    """Minimal fluent recorder for the update/insert/select chains create_posts +
    verify_posts drive. Records update payloads for assertions."""

    def __init__(self, store):
        self._store = store
        self._table = None
        self._update = None

    def table(self, name):
        self._table = name
        return self

    def update(self, fields):
        self._update = fields
        return self

    def eq(self, col, val):
        if self._update is not None:
            self._store.setdefault("updates", []).append(
                {"table": self._table, "col": col, "val": val, "fields": self._update}
            )
            self._update = None
        return self

    def execute(self):
        class _R:
            data = []
        return _R()


def _base_client():
    return {"id": "c1", "name": "Acme", "website_url": "https://acme.com",
            "business_location": "Denver, CO", "gbp": {}, "rank_tracking_location_code": 2840}


def _set_with_items(items, service_page_url="https://acme.com/metal-roof-repair/"):
    return {
        "id": "set1", "client_id": "c1", "service_keyword": "metal roof repair",
        "location": "Denver, CO", "geo_mode": "geo",
        "service_page_url": service_page_url, "status": "draft", "items": items,
    }


def _patch_common(monkeypatch, store, *, gates=None, gbp_id=None):
    async def fake_preflight(set_id, acknowledge=False):
        return {"gates": gates or [], "chosen_count": 2,
                "slug_collisions": [], "existing_site_matches": []}

    monkeypatch.setattr(svc, "preflight", fake_preflight)
    monkeypatch.setattr(svc, "_client", lambda cid: _base_client())
    monkeypatch.setattr(svc, "_sb", lambda: _FakeChain(store))
    monkeypatch.setattr(svc, "_create_gbp_post", lambda *a, **k: gbp_id)
    monkeypatch.setattr(svc, "_refresh_syndication", lambda cid: None)

    created = []

    def fake_create_run(**kwargs):
        created.append(kwargs)
        return f"run-{len(created)}"

    monkeypatch.setattr(svc, "create_run_and_snapshot", fake_create_run)
    return created


async def test_create_posts_one_run_per_paa_seeded_from_exact_string(monkeypatch):
    store = {}
    items = [
        {"id": "i1", "question": "How much does metal roof repair cost?", "chosen": True, "slug": "s1"},
        {"id": "i2", "question": "Is metal roof repair worth it?", "chosen": True, "slug": "s2"},
    ]
    monkeypatch.setattr(svc, "get_set", lambda sid: _set_with_items(items))
    created = _patch_common(monkeypatch, store)

    result = await svc.create_posts("set1", user_id="u1", acknowledge=False)

    assert result["blocked"] is False
    assert result["created"] == 2 and len(result["run_ids"]) == 2

    # One run per chosen PAA, keyword == the EXACT PAA string (rule 1 + rule 2 seed).
    assert [c["keyword"] for c in created] == [
        "How much does metal roof repair cost?",
        "Is metal roof repair worth it?",
    ]
    for c, it in zip(created, items):
        assert c["content_type"] == "blog_post"
        # Idempotent per item.
        assert c["source_ref"] == f"paa_item:{it['id']}"
        # writer_notes carry all three rules incl. the service-page link (rule 3).
        notes = c["writer_notes"]
        assert it["question"] in notes
        assert "https://acme.com/metal-roof-repair/" in notes
        assert "one question, one post" in notes.lower()

    # The run_id was written back onto each item.
    item_updates = [u for u in store["updates"] if u["table"] == "paa_items"]
    assert {u["val"] for u in item_updates} == {"i1", "i2"}
    assert all("run_id" in u["fields"] for u in item_updates)
    # The set was activated.
    assert any(u["table"] == "paa_sets" and u["fields"].get("status") == "active"
               for u in store["updates"])


async def test_create_posts_blocked_by_cannibalization_gate_creates_nothing(monkeypatch):
    store = {}
    items = [{"id": "i1", "question": "q1", "chosen": True, "slug": "s1"}]
    monkeypatch.setattr(svc, "get_set", lambda sid: _set_with_items(items))
    created = _patch_common(
        monkeypatch, store,
        gates=[{"kind": "paa_slug_collision", "message": "reused", "blocking": True, "acknowledgeable": True}],
    )

    result = await svc.create_posts("set1", user_id="u1", acknowledge=False)

    assert result["blocked"] is True
    assert result["run_ids"] == []
    assert created == []  # no runs created while blocked
    assert "updates" not in store  # nothing written


async def test_create_posts_records_gbp_when_created(monkeypatch):
    store = {}
    items = [{"id": "i1", "question": "q1", "chosen": True, "slug": "s1"}]
    monkeypatch.setattr(svc, "get_set", lambda sid: _set_with_items(items))
    _patch_common(monkeypatch, store, gbp_id="gbp-1")

    result = await svc.create_posts("set1", user_id="u1", acknowledge=False)
    assert result["gbp_created"] == 1
    item_update = [u for u in store["updates"] if u["table"] == "paa_items"][0]
    assert item_update["fields"]["gbp_post_id"] == "gbp-1"


def test_verify_posts_runs_checks_on_completed_and_leaves_pending(monkeypatch):
    store = {}
    items = [
        {"id": "i1", "question": "How much does metal roof repair cost?", "chosen": True, "run_id": "run-1"},
        {"id": "i2", "question": "Is metal roof repair worth it?", "chosen": True, "run_id": None},
    ]
    monkeypatch.setattr(svc, "get_set", lambda sid: _set_with_items(items))
    monkeypatch.setattr(svc, "_sb", lambda: _FakeChain(store))

    def fake_article(run_id):
        # Completed run: title states the exact PAA + links the service page.
        return {
            "html": '<h1>How much does metal roof repair cost?</h1>'
                    '<a href="https://acme.com/metal-roof-repair/">svc</a>',
            "title": "How much does metal roof repair cost?",
            "h1": "How much does metal roof repair cost?",
            "headings": [],
        }

    monkeypatch.setattr(svc, "_article_for_run", fake_article)

    result = svc.verify_posts("set1")
    assert result["verified"] == 1 and result["pending"] == 1

    upd = [u for u in store["updates"] if u["table"] == "paa_items"][0]
    checks = upd["fields"]["checks"]
    assert checks["exact_match"]["ok"] is True
    assert checks["service_link"]["ok"] is True


def test_verify_posts_pending_when_run_not_complete(monkeypatch):
    store = {}
    items = [{"id": "i1", "question": "q1", "chosen": True, "run_id": "run-1"}]
    monkeypatch.setattr(svc, "get_set", lambda sid: _set_with_items(items))
    monkeypatch.setattr(svc, "_sb", lambda: _FakeChain(store))
    monkeypatch.setattr(svc, "_article_for_run", lambda rid: None)  # sources_cited not ready

    result = svc.verify_posts("set1")
    assert result["verified"] == 0 and result["pending"] == 1
    assert "updates" not in store
