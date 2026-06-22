"""Tests for advisory AIO proximity (aio_proximity.py, §X.5).

Embeddings are injected for exact, deterministic cosines.
"""

from __future__ import annotations

import math

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
