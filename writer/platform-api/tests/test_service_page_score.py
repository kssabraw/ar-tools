"""Tests for the Service Page scoring / reoptimization service (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from services import service_page_score as sps

_PFX = "services.service_page_score"


# ---- pure helpers ----

def test_build_scoring_html_wraps_title_and_h1():
    html = sps.build_scoring_html({
        "title": "Emergency Plumber",
        "primary_query": "emergency plumber",
        "renderings": {"html": "<h2>Fast response</h2><p>We come quickly.</p>"},
    })
    assert "<title>Emergency Plumber</title>" in html
    assert "<h1>Emergency Plumber</h1>" in html
    assert "<h2>Fast response</h2>" in html


def test_business_fields_prefers_gbp_then_name():
    assert sps._business_fields({"gbp": {"business_name": "Acme Co", "gbp_category": "Plumber"}}) == ("Acme Co", "Plumber")
    assert sps._business_fields({"name": "Bob LLC"}) == ("Bob LLC", "")


# ---- fake supabase (query-builder shim) ----

class _FakeChain:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self._insert = None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def single(self): return self

    def insert(self, row):
        self._insert = row
        self.store.setdefault("inserts", []).append((self.table, row))
        return self

    def execute(self):
        if self._insert is not None:
            return MagicMock(data=[{"id": "new-id"}])
        return MagicMock(data=self.store["select"].get(self.table))


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeChain(name, self.store)


def _store():
    return {
        "select": {
            "runs": {"id": "r1", "content_type": "service_page", "client_id": "c1", "keyword": "emergency plumber"},
            "clients": {"name": "Acme Co", "gbp": {"gbp_category": "Plumber"}},
            "module_outputs": [{"id": "mo1", "attempt_number": 1,
                                "output_payload": {"title": "Emergency Plumber", "primary_query": "emergency plumber",
                                                   "sections": [{"heading": "Our Promise"}],
                                                   "renderings": {"html": "<h2>x</h2>"},
                                                   "metadata": {"cost_usd": 0.05}}}],
            "client_context_snapshots": [{"brand_guide_text": "b", "icp_text": "i", "website_analysis": None,
                                          "website_analysis_unavailable": True}],
        },
    }


_SCORE = {"composite_score": 72.0, "composite_status": "needs_improvement",
          "engine_scores": {}, "deficiencies": [{"engine": "AEO", "engine_key": "aeo_llm_retrieval",
                                                  "issues": ["no FAQ"], "recommendations": ["add FAQ"]}],
          "token_usage": {"cost_usd": 0.013}}


async def test_score_run_calls_nlp_national_and_persists():
    store = _store()
    with patch(f"{_PFX}._sb", return_value=_FakeSB(store)), \
         patch(f"{_PFX}._post_nlp", AsyncMock(return_value=_SCORE)) as post_nlp:
        result = await sps.score_run("r1", user_id="u1")

    assert result["composite_score"] == 72.0
    # nlp called in national mode with the wrapped HTML
    args, kwargs = post_nlp.call_args
    assert args[0] == "/score-page"
    assert args[1]["geo_mode"] == "national"
    assert "emergency plumber" in args[1]["keyword"]
    # a service_score row was persisted
    assert any(t == "module_outputs" and r["module"] == "service_score" for t, r in store["inserts"])


async def test_reoptimize_run_regenerates_then_rescores():
    store = _store()
    page = {"title": "Emergency Plumber", "renderings": {"html": "<h2>better</h2>"},
            "metadata": {"cost_usd": 0.07, "schema_version": "1.0"}}
    with patch(f"{_PFX}._sb", return_value=_FakeSB(store)), \
         patch(f"{_PFX}._post_pipeline", AsyncMock(return_value=page)) as post_pipeline, \
         patch(f"{_PFX}._post_nlp", AsyncMock(return_value=_SCORE)):
        out = await sps.reoptimize_run("r1", [{"engine_key": "aeo_llm_retrieval"}], user_id="u1")

    # pipeline called in reoptimize mode
    args, _ = post_pipeline.call_args
    assert args[0] == "/service-write"
    assert args[1]["mode"] == "reoptimize"
    assert args[1]["deficiencies"] == [{"engine_key": "aeo_llm_retrieval"}]
    assert out["page"] == page and out["score"]["composite_score"] == 72.0
    # new service_writer attempt + a service_score were persisted
    inserted_modules = [r["module"] for t, r in store["inserts"] if t == "module_outputs"]
    assert "service_writer" in inserted_modules
    assert "service_score" in inserted_modules
