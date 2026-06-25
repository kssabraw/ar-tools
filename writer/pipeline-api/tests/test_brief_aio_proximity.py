"""Tests for advisory AIO proximity (aio_proximity.py, §X.5).

Embeddings are injected for exact, deterministic cosines.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest

from modules.brief.aio_proximity import compute_aio_proximity


def _unit(scale: float) -> list[float]:
    """Vector along axis 0 with cosine == scale to the answer vector (which
    is pure axis 0)."""
    x = scale
    y = math.sqrt(max(0.0, 1.0 - x * x))
    return [x, y, 0.0]


def _embedder(scale_by_substr: dict[str, float], default: float = 0.5):
    async def _embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if t == "ANSWER":
                out.append([1.0, 0.0, 0.0])
                continue
            scale = default
            for key, sc in scale_by_substr.items():
                if key in t.lower():
                    scale = sc
                    break
            out.append(_unit(scale))
        return out
    return _embed


@pytest.mark.asyncio
async def test_none_when_no_answer_text():
    pm, cov = await compute_aio_proximity(
        heading_texts=["A", "B"], fanout_questions=[], answer_text="",
        embed_fn=_embedder({}),
    )
    assert pm is None and cov is None


@pytest.mark.asyncio
async def test_none_when_no_headings():
    pm, cov = await compute_aio_proximity(
        heading_texts=[], fanout_questions=["q"], answer_text="ANSWER",
        embed_fn=_embedder({}),
    )
    assert pm is None and cov is None


@pytest.mark.asyncio
async def test_proximity_mean_is_average_cosine():
    embed = _embedder({"near": 0.9, "far": 0.3})
    pm, cov = await compute_aio_proximity(
        heading_texts=["near heading", "far heading"],
        fanout_questions=[],
        answer_text="ANSWER",
        embed_fn=embed,
    )
    assert pm == pytest.approx(0.6, abs=1e-3)  # (0.9 + 0.3) / 2
    assert cov is None


@pytest.mark.asyncio
async def test_fanout_coverage_counts_covered_questions():
    # Heading "topic" at 0.9 to answer; fanout q1 shares "topic" so it's
    # close to the heading (cosine 1.0 since same vector); q2 is "other" at
    # 0.1 -> far from the heading -> not covered.
    embed = _embedder({"topic": 0.9, "other": 0.1})
    pm, cov = await compute_aio_proximity(
        heading_texts=["topic heading"],
        fanout_questions=["a topic question", "an other question"],
        answer_text="ANSWER",
        embed_fn=embed,
        coverage_threshold=0.6,
    )
    # q1 ("topic") vs heading ("topic") -> same vector -> cosine 1.0 covered;
    # q2 ("other", 0.1) vs heading (0.9) -> cosine ~0.52 < 0.6 -> not covered.
    # 1 of 2 covered = 0.5
    assert cov == pytest.approx(0.5, abs=1e-3)


@pytest.mark.asyncio
async def test_no_fanout_yields_none_coverage_but_real_proximity():
    embed = _embedder({"h": 0.8})
    pm, cov = await compute_aio_proximity(
        heading_texts=["h one", "h two"],
        fanout_questions=[],
        answer_text="ANSWER",
        embed_fn=embed,
    )
    assert pm == pytest.approx(0.8, abs=1e-3)
    assert cov is None


# ---- Dual-space (Gemini) routing (v2.8) ----

_PREFIX = "modules.brief.aio_proximity"


@pytest.mark.asyncio
async def test_dual_space_used_when_gemini_configured_and_no_embed_fn():
    # headings → RETRIEVAL_QUERY; [answer, *fanout] → RETRIEVAL_DOCUMENT.
    q = AsyncMock(return_value=[[1.0, 0.0, 0.0]])           # one heading, aligned
    d = AsyncMock(return_value=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])  # answer aligned, fanout orthogonal
    with patch(f"{_PREFIX}.gemini_configured", return_value=True), \
         patch(f"{_PREFIX}.embed_gemini_query", q), \
         patch(f"{_PREFIX}.embed_gemini_document", d), \
         patch(f"{_PREFIX}.embed_batch_large", AsyncMock(side_effect=AssertionError("fallback must not run"))):
        pm, cov = await compute_aio_proximity(
            heading_texts=["heading"],
            fanout_questions=["q1"],
            answer_text="ANSWER",
            coverage_threshold=0.6,
        )
    q.assert_awaited_once_with(["heading"])
    d.assert_awaited_once_with(["ANSWER", "q1"])
    assert pm == pytest.approx(1.0, abs=1e-3)   # heading == answer
    assert cov == pytest.approx(0.0, abs=1e-3)  # fanout orthogonal to heading


@pytest.mark.asyncio
async def test_falls_back_to_openai_when_gemini_errors():
    fallback = _embedder({"h": 0.7})
    with patch(f"{_PREFIX}.gemini_configured", return_value=True), \
         patch(f"{_PREFIX}.embed_gemini_query", AsyncMock(side_effect=RuntimeError("gemini down"))), \
         patch(f"{_PREFIX}.embed_gemini_document", AsyncMock(return_value=[])), \
         patch(f"{_PREFIX}.embed_batch_large", fallback):
        pm, cov = await compute_aio_proximity(
            heading_texts=["h one"],
            fanout_questions=[],
            answer_text="ANSWER",
        )
    assert pm == pytest.approx(0.7, abs=1e-3)  # came from the OpenAI fallback embedder


@pytest.mark.asyncio
async def test_single_space_when_gemini_not_configured():
    fallback = _embedder({"h": 0.6})
    with patch(f"{_PREFIX}.gemini_configured", return_value=False), \
         patch(f"{_PREFIX}.embed_gemini_query", AsyncMock(side_effect=AssertionError("gemini must not run"))), \
         patch(f"{_PREFIX}.embed_batch_large", fallback):
        pm, cov = await compute_aio_proximity(
            heading_texts=["h one"],
            fanout_questions=[],
            answer_text="ANSWER",
        )
    assert pm == pytest.approx(0.6, abs=1e-3)


# ---- GeminiEmbedder unit (config guard + payload/normalization) ----


@pytest.mark.asyncio
async def test_embed_gemini_raises_without_key():
    from modules.brief import llm

    with patch.object(llm.settings, "gemini_api_key", ""):
        with pytest.raises(RuntimeError):
            await llm.embed_gemini(["x"], task_type="RETRIEVAL_QUERY")


@pytest.mark.asyncio
async def test_embed_gemini_normalizes_and_sends_task_type():
    from modules.brief import llm

    captured: dict = {}

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            # Two un-normalized 3-vectors; embed_gemini must L2-normalize them.
            return {"embeddings": [{"values": [3.0, 4.0, 0.0]}, {"values": [0.0, 0.0, 5.0]}]}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResp()

    with patch.object(llm.settings, "gemini_api_key", "test-key"), \
         patch.object(llm.settings, "gemini_embedding_model", "gemini-embedding-001"), \
         patch.object(llm.settings, "gemini_embedding_dim", 3), \
         patch.object(llm.httpx, "AsyncClient", _FakeClient):
        vecs = await llm.embed_gemini(["a", "b"], task_type="RETRIEVAL_DOCUMENT")

    assert vecs == [pytest.approx([0.6, 0.8, 0.0]), pytest.approx([0.0, 0.0, 1.0])]
    assert "models/gemini-embedding-001:batchEmbedContents" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert all(r["taskType"] == "RETRIEVAL_DOCUMENT" for r in captured["json"]["requests"])
    assert all(r["outputDimensionality"] == 3 for r in captured["json"]["requests"])
