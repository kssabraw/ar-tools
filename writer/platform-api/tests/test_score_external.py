"""Tests for the run-free 'Score an existing page' path (Blog + Service).

Covers the standalone `score_external_client` scorers (no run, no persistence,
entity_provider threaded, geo handling) and the `score_external` job dispatch
(result stored on the job row; failures recorded, never raised)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services import blog_page_score as bps
from services import service_page_score as sps
from services import score_external


# ---- fake supabase (single-row select shim, reused from the score tests) ----

class _Chain:
    def __init__(self, table, store):
        self.table = table
        self.store = store

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def single(self): return self

    def execute(self):
        return MagicMock(data=self.store.get(self.table))


class _SB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Chain(name, self.store)


_SCORE = {
    "composite_score": 68.0,
    "composite_status": "needs_improvement",
    "engine_scores": {"entity_establishment": {"score": 55, "entities_missing": ["Roofing", "Metal Roof"]}},
    "deficiencies": [{"engine": "Entity", "engine_key": "entity_establishment"}],
    "token_usage": {"cost_usd": 0.011},
}


# ---- blog: run-free score ----

async def test_blog_score_external_national_threads_entity_provider_no_persist():
    store = {"clients": {"name": "Acme Roofing", "gbp": {"gbp_category": "Roofer"}}}
    with patch("services.blog_page_score._sb", return_value=_SB(store)), \
         patch("services.blog_page_score._post_nlp", AsyncMock(return_value=_SCORE)) as post_nlp, \
         patch("services.voice_card_service.get_voice_card", AsyncMock(return_value={})), \
         patch("services.blog_page_score._insert_output") as insert_output:
        result = await bps.score_external_client(
            "c1", "best metal roofs",
            source_html="<h1>Metal Roofs</h1><p>Guide.</p>",
            entity_provider="google",
        )

    assert result["composite_score"] == 68.0
    args, _ = post_nlp.call_args
    assert args[0] == "/score-blog-page"
    assert args[1]["geo_mode"] == "national"
    assert args[1]["entity_provider"] == "google"
    assert args[1]["page_content"].startswith("<h1>")
    # A run-free check persists nothing.
    insert_output.assert_not_called()


async def test_blog_score_external_empty_source_raises():
    store = {"clients": {"name": "Acme"}}
    with patch("services.blog_page_score._sb", return_value=_SB(store)), \
         patch("services.voice_card_service.get_voice_card", AsyncMock(return_value={})):
        with pytest.raises(HTTPException) as ei:
            await bps.score_external_client("c1", "kw", source_html="   ")
    assert ei.value.detail == "source_page_empty"


# ---- service: run-free score, geo handling ----

async def test_service_score_external_service_page_is_national():
    store = {"clients": {"name": "Acme", "gbp": {"gbp_category": "Plumber", "address": "1 Main St"}}}
    with patch("services.service_page_score._sb", return_value=_SB(store)), \
         patch("services.service_page_score._post_nlp", AsyncMock(return_value=_SCORE)) as post_nlp, \
         patch("services.voice_card_service.get_voice_card", AsyncMock(return_value={})):
        await sps.score_external_client(
            "c1", "emergency plumber", "service_page",
            source_html="<h1>Plumber</h1>", entity_provider="google",
        )
    args, _ = post_nlp.call_args
    assert args[0] == "/score-page"
    assert args[1]["geo_mode"] == "national"
    assert args[1]["entity_provider"] == "google"
    assert "location" not in args[1]


async def test_service_score_external_location_page_is_local_with_area():
    store = {"clients": {"name": "Acme", "gbp": {"gbp_category": "Plumber", "address": "1 Main St, Austin"}}}
    with patch("services.service_page_score._sb", return_value=_SB(store)), \
         patch("services.service_page_score._post_nlp", AsyncMock(return_value=_SCORE)) as post_nlp, \
         patch("services.voice_card_service.get_voice_card", AsyncMock(return_value={})):
        await sps.score_external_client(
            "c1", "emergency plumber austin", "location_page",
            source_html="<h1>Austin Plumber</h1>",
            location="Austin, TX", location_code=2840,
        )
    payload = post_nlp.call_args[0][1]
    assert payload["geo_mode"] == "local"
    assert payload["location"] == "Austin, TX"
    assert payload["location_code"] == 2840
    assert payload["address"] == "1 Main St, Austin"


# ---- job dispatch ----

class _JobsChain:
    def __init__(self, store):
        self.store = store
        self._update = None

    def update(self, row):
        self._update = row
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        if self._update is not None:
            self.store.setdefault("updates", []).append(self._update)
        return MagicMock(data=self.store.get("rows"))


class _JobsSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _JobsChain(self.store)


async def test_run_job_blog_stores_result():
    store: dict = {}
    job = {"id": "j1", "payload": {"tool": "blog", "client_id": "c1", "keyword": "kw",
                                   "page_content": "<h1>x</h1>", "entity_provider": "google"}}
    with patch("services.score_external.get_supabase", return_value=_JobsSB(store)), \
         patch("services.blog_page_score.score_external_client", AsyncMock(return_value=_SCORE)) as scorer:
        await score_external.run_job(job)

    scorer.assert_awaited_once()
    assert store["updates"][-1]["status"] == "complete"
    assert store["updates"][-1]["result"]["composite_score"] == 68.0


async def test_run_job_records_http_detail_on_failure():
    store: dict = {}
    job = {"id": "j1", "payload": {"tool": "service", "client_id": "c1", "keyword": "kw",
                                   "page_type": "service_page", "page_content": "   "}}
    with patch("services.score_external.get_supabase", return_value=_JobsSB(store)), \
         patch("services.service_page_score.score_external_client",
               AsyncMock(side_effect=HTTPException(status_code=422, detail="source_page_empty"))):
        await score_external.run_job(job)

    assert store["updates"][-1]["status"] == "failed"
    assert store["updates"][-1]["error"] == "source_page_empty"


async def test_run_job_missing_client_fails_fast():
    store: dict = {}
    with patch("services.score_external.get_supabase", return_value=_JobsSB(store)):
        await score_external.run_job({"id": "j1", "payload": {"tool": "blog", "keyword": "kw"}})
    assert store["updates"][-1]["status"] == "failed"
    assert store["updates"][-1]["error"] == "missing_client"


def test_enqueue_rejects_unknown_tool():
    with pytest.raises(HTTPException):
        score_external.enqueue("c1", "wordpress", {"keyword": "kw"})
