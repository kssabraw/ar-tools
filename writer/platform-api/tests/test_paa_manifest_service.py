"""Impure-layer tests for PAA → SEO Neo Phase 2 (services/paa_manifest_service.py)
with mocks — the QA job (QA-Agent path + the deterministic fallback), the
export assembly, and the Google-Sheet hand-off. No network / no DB."""

import pytest

from services import paa_manifest_service as svc


class _R:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """Minimal fluent recorder routing select/update/insert/delete by table."""

    def __init__(self, name, sb):
        self.name, self.sb = name, sb
        self._op = None
        self._payload = None
        self._eq = {}

    def select(self, *a, **k):
        self._op = "select"; return self

    def update(self, payload):
        self._op = "update"; self._payload = payload; return self

    def insert(self, payload):
        self._op = "insert"; self._payload = payload; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, col, val):
        self._eq[col] = val; return self

    def in_(self, col, vals):
        self._eq[col] = ("in", vals); return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self._op == "select":
            if self.name == "paa_manifests":
                return _R([{"id": "m1", "set_id": "set1", "client_id": "c1"}])
            if self.name == "paa_manifest_assets":
                return _R(list(self.sb.assets))
            if self.name == "paa_items":
                iid = self._eq.get("id")
                return _R([{"checks": self.sb.item_checks.get(iid)}] if iid in self.sb.item_checks else [])
            return _R([])
        if self._op == "update":
            if self.name == "paa_manifest_assets":
                self.sb.store.setdefault("asset_updates", []).append(
                    {"id": self._eq.get("id"), "fields": self._payload})
            elif self.name == "paa_manifests":
                self.sb.store.setdefault("manifest_updates", []).append(self._payload)
            return _R([])
        return _R([])


class _FakeSB:
    def __init__(self, store, assets, item_checks=None):
        self.store, self.assets, self.item_checks = store, assets, item_checks or {}

    def table(self, name):
        return _FakeTable(name, self)


def _set_row():
    return {"id": "set1", "client_id": "c1", "service_keyword": "metal roof repair",
            "location": "Denver, CO"}


def _client():
    return {"id": "c1", "name": "Acme", "website_url": "https://acme.com", "gbp": {}}


# ── QA job — the QA-Agent path ────────────────────────────────────────────────


async def test_qa_job_reviews_content_urls_via_agent(monkeypatch):
    store = {}
    assets = [
        {"id": "a1", "category": "paa_post", "url": "https://acme.com/q1/", "paa_item_id": "i1"},
        {"id": "a2", "category": "gbp_post", "url": "https://maps.google.com/p", "paa_item_id": "i1"},
        {"id": "a3", "category": "authority", "url": None, "paa_item_id": None},
    ]
    monkeypatch.setattr(svc.settings, "qa_enabled", True)
    monkeypatch.setattr(svc, "_set", lambda sid: _set_row())
    monkeypatch.setattr(svc, "_client", lambda cid: _client())
    monkeypatch.setattr(svc, "_sb", lambda: _FakeSB(store, assets))
    recompute = {"called": 0}
    monkeypatch.setattr(svc, "_recompute_summaries", lambda mid: recompute.__setitem__("called", recompute["called"] + 1))

    calls = []

    async def fake_review_url(url, client=None, rubric=None, keyword=None):
        calls.append({"url": url, "rubric": rubric, "keyword": keyword})
        return {"verdict": "advisory", "rubric": rubric, "composite": 82,
                "issues": [], "narrative": "looks fine"}

    from services import qa_service
    monkeypatch.setattr(qa_service, "review_url", fake_review_url)

    await svc.run_manifest_qa_job({"payload": {"manifest_id": "m1"}})

    # Only the page-like PAA post is reviewed (gbp_post/image aren't URL-gradeable;
    # the authority row is not a content asset).
    assert [c["url"] for c in calls] == ["https://acme.com/q1/"]
    assert calls[0]["rubric"] == "blog" and calls[0]["keyword"] == "metal roof repair"

    upd = {u["id"]: u["fields"] for u in store["asset_updates"]}
    assert upd["a1"]["qa_verdict"] == "advisory"
    assert upd["a1"]["qa_review"]["mode"] == "qa_agent"
    assert "a2" not in upd and "a3" not in upd
    # Reviewed → manifest marked ready + summaries recomputed.
    assert any(m.get("status") == "ready" for m in store["manifest_updates"])
    assert recompute["called"] == 1


# ── QA job — deterministic fallback (QA Agent off) ────────────────────────────


async def test_qa_job_deterministic_fallback_when_agent_disabled(monkeypatch):
    store = {}
    assets = [{"id": "a1", "category": "paa_post", "url": "https://acme.com/q1/",
               "paa_item_id": "i1"}]
    item_checks = {"i1": {"exact_match": {"ok": True}, "service_link": {"ok": True}}}
    monkeypatch.setattr(svc.settings, "qa_enabled", False)
    monkeypatch.setattr(svc, "_set", lambda sid: _set_row())
    monkeypatch.setattr(svc, "_client", lambda cid: _client())
    monkeypatch.setattr(svc, "_sb", lambda: _FakeSB(store, assets, item_checks))
    monkeypatch.setattr(svc, "_recompute_summaries", lambda mid: None)

    await svc.run_manifest_qa_job({"payload": {"manifest_id": "m1"}})

    upd = {u["id"]: u["fields"] for u in store["asset_updates"]}
    assert upd["a1"]["qa_verdict"] == "pass"          # both v1 checks cleared
    assert upd["a1"]["qa_review"]["mode"] == "deterministic"


def test_deterministic_verdict():
    assert svc._deterministic_verdict({"exact_match": {"ok": True}, "service_link": {"ok": True}}) == "pass"
    assert svc._deterministic_verdict({"exact_match": {"ok": True}, "service_link": {"ok": None}}) == "pass"
    assert svc._deterministic_verdict({"exact_match": {"ok": False}, "service_link": {"ok": True}}) == "revisions"
    assert svc._deterministic_verdict(None) is None


# ── export ────────────────────────────────────────────────────────────────────


def _manifest_view():
    return {
        "exists": True,
        "manifest": {"id": "m1", "client_id": "c1", "status": "ready"},
        "assets": [
            {"category": "paa_post", "source": "auto", "label": "PAA post — q",
             "url": "https://acme.com/q/", "status": "collected", "confidence_tag": None,
             "qa_verdict": "pass", "cost_task_type": None, "cost_quantity": None, "note": ""},
            {"category": "authority", "source": "seed", "label": "GMBB Blast", "url": None,
             "status": "planned", "confidence_tag": "PROVEN", "qa_verdict": None,
             "cost_task_type": "gbp_blast", "cost_quantity": 1, "note": "map-only"},
        ],
        "client_identity": {"business_name": "Acme", "place_id": "ChIJ1", "address": "",
                            "phone": "", "cid": "", "gbp_url": "", "website": ""},
        "service_keyword": "metal roof repair", "location": "Denver, CO",
        "cost_summary": {"estimated_total": 5.0}, "qa_summary": {"worst": "pass"},
    }


def test_build_export_assembles_rows_and_payload(monkeypatch):
    monkeypatch.setattr(svc, "get_manifest", lambda **k: _manifest_view())
    export = svc.build_export("m1")
    assert export["title"].startswith("PAA Prep Sheet — metal roof repair")
    flat = "\n".join("|".join(str(c) for c in r) for r in export["rows"])
    assert "ChIJ1" in flat and "GMBB Blast" in flat
    assert export["payload"]["service_keyword"] == "metal roof repair"
    assert export["payload"]["qa_summary"]["worst"] == "pass"


async def test_export_to_sheet_writes_refs_and_marks_handed_off(monkeypatch):
    store = {}
    monkeypatch.setattr(svc, "get_manifest", lambda **k: _manifest_view())
    monkeypatch.setattr(svc, "_client", lambda cid: {"id": "c1", "google_drive_folder_id": "folder1"})
    monkeypatch.setattr(svc, "_sb", lambda: _FakeSB(store, []))

    from services import google_docs
    monkeypatch.setattr(google_docs, "resolve_drive_folder", lambda c, t: "folder1")

    async def fake_sheet(folder, title, rows, share="private", dedupe_by_name=False):
        return {"sheet_id": "sh1", "sheet_url": "https://sheets/sh1", "reused": False}

    monkeypatch.setattr(google_docs, "create_google_sheet", fake_sheet)

    res = await svc.export_to_sheet("m1")
    assert res["sheet_url"] == "https://sheets/sh1"
    upd = store["manifest_updates"][0]
    assert upd["sheet_id"] == "sh1" and upd["status"] == "handed_off"


async def test_export_to_sheet_requires_drive_folder(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(svc, "get_manifest", lambda **k: _manifest_view())
    monkeypatch.setattr(svc, "_client", lambda cid: {"id": "c1"})
    from services import google_docs
    monkeypatch.setattr(google_docs, "resolve_drive_folder", lambda c, t: None)

    with pytest.raises(HTTPException) as exc:
        await svc.export_to_sheet("m1")
    assert exc.value.detail == "missing_google_drive_folder_id"
