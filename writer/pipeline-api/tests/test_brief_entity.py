"""Tests for main-entity derivation (entity.py, PRD §X.2 / §13.X.8).

Pure / fixture-runnable: spaCy is local and deterministic, and embeddings
are injected via a fake `embed_fn`, so no network or LLM is touched.
"""

from __future__ import annotations

import math

import pytest

from modules.brief.entity import (
    KEYWORD_SANITY_FLOOR,
    derive_main_entity,
)


# ---------------------------------------------------------------------------
# Fake embeddings - deterministic, keyed by simple token overlap so cosine
# behaves intuitively for the tie-break / sanity / fallback paths.
# ---------------------------------------------------------------------------

def _vec(text: str) -> list[float]:
    """A crude bag-of-chars vector over a fixed alphabet - deterministic and
    good enough for relative cosine comparisons in tests."""
    text = text.lower()
    dims = "abcdefghijklmnopqrstuvwxyz0123456789 "
    v = [float(text.count(ch)) for ch in dims]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


async def fake_embed(texts: list[str]) -> list[list[float]]:
    return [_vec(t) for t in texts]


def _high_sanity_embed(entity_like: str):
    """Embed fn where anything sharing tokens with `entity_like` is very
    close to the keyword (forces sanity pass), used to isolate extraction."""
    async def _embed(texts: list[str]) -> list[list[float]]:
        return [_vec(t) for t in texts]
    return _embed


# ---------------------------------------------------------------------------
# (a) "327 angel number" query -> canonical "angel number 327", query form
#     present in variants.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aio_number_entity_canonical_and_variants():
    answer = (
        "The angel number 327 signals growth. Angel number 327 encourages "
        "trust in your path. The angel number 327 appears when change is near. "
        "Many people see 327 angel number during transitions."
    )
    result = await derive_main_entity(
        primary_keyword="angel number 327",
        title="Angel Number 327 Meaning and Symbolism",
        aio_answer_text=answer,
        aio_present=True,
        embed_fn=fake_embed,
    )
    assert result.source == "aio"
    # head noun is "number"; the number-adjacency extension keeps "327".
    assert "327" in result.canonical
    assert "angel number" in result.canonical.lower()


# ---------------------------------------------------------------------------
# (b) generic-head suppression: "benefits" must not beat
#     "magnesium glycinate benefits".
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generic_head_suppressed():
    answer = (
        "Magnesium glycinate benefits sleep and calm. The benefits are clear. "
        "Magnesium glycinate benefits include better rest. These benefits "
        "matter. Magnesium glycinate benefits the nervous system."
    )
    result = await derive_main_entity(
        primary_keyword="magnesium glycinate benefits",
        title="Magnesium Glycinate Benefits for Sleep",
        aio_answer_text=answer,
        aio_present=True,
        embed_fn=fake_embed,
    )
    assert result.source == "aio"
    assert "magnesium glycinate" in result.canonical.lower()
    assert result.canonical.lower() != "benefits"


# ---------------------------------------------------------------------------
# (c) comparison answer -> multi_entity_flag + title tie-break.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_comparison_sets_multi_entity_flag():
    answer = (
        "Notion is a flexible workspace. Notion suits docs. "
        "Obsidian is a local note app. Obsidian suits markdown."
    )
    result = await derive_main_entity(
        primary_keyword="notion vs obsidian",
        title="Notion vs Obsidian: Which Note App Wins",
        aio_answer_text=answer,
        aio_present=True,
        embed_fn=fake_embed,
    )
    # Two roughly co-equal subjects => low confidence => multi-entity.
    assert result.multi_entity_flag is True


# ---------------------------------------------------------------------------
# (d) sub-0.45 sanity failure falls back to title.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sanity_failure_falls_back_to_title():
    # Answer is about something unrelated to the keyword; sanity cosine low.
    answer = (
        "Photosynthesis converts light to energy. Photosynthesis sustains "
        "plants. Photosynthesis drives growth. Photosynthesis is vital."
    )

    async def low_sanity_embed(texts: list[str]) -> list[list[float]]:
        # Force orthogonal vectors between entity-ish and keyword so cosine
        # is ~0 (< floor), triggering fallback.
        out = []
        for t in texts:
            if "loan" in t.lower():
                out.append(_vec("loan mortgage finance keyword"))
            else:
                out.append(_vec("zzz qqq xxx"))
        return out

    result = await derive_main_entity(
        primary_keyword="best mortgage loan rates",
        title="Best Mortgage Loan Rates 2026",
        aio_answer_text=answer,
        aio_present=True,
        embed_fn=low_sanity_embed,
    )
    assert result.source == "title_fallback"


# ---------------------------------------------------------------------------
# (e) AIO-absent brief -> title_fallback deterministically.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aio_absent_uses_title_fallback():
    result = await derive_main_entity(
        primary_keyword="crystal cleansing",
        title="How to Cleanse Crystals at Home",
        aio_answer_text=None,
        aio_present=False,
        embed_fn=fake_embed,
    )
    assert result.source == "title_fallback"
    assert result.canonical  # always populated


@pytest.mark.asyncio
async def test_empty_answer_with_present_flag_falls_back():
    result = await derive_main_entity(
        primary_keyword="crystal cleansing",
        title="How to Cleanse Crystals at Home",
        aio_answer_text="   ",
        aio_present=True,
        embed_fn=fake_embed,
    )
    assert result.source == "title_fallback"


# ---------------------------------------------------------------------------
# (f) brand/site exclusion: a repeated cited brand isn't the entity.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_brand_excluded_from_candidates():
    answer = (
        "Creatine builds muscle. Creatine improves strength. "
        "Creatine supports recovery. Creatine is well studied."
    )
    result = await derive_main_entity(
        primary_keyword="creatine benefits",
        title="Creatine Benefits and Uses",
        aio_answer_text=answer,
        aio_cited_domains=["healthline.com", "webmd.com"],
        aio_present=True,
        embed_fn=fake_embed,
    )
    assert "healthline" not in result.canonical.lower()
    assert "creatine" in result.canonical.lower()


# ---------------------------------------------------------------------------
# (g) determinism: same input -> same output.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_determinism():
    kwargs = dict(
        primary_keyword="angel number 327",
        title="Angel Number 327 Meaning",
        aio_answer_text=(
            "Angel number 327 means growth. Angel number 327 signals trust. "
            "Angel number 327 appears in transitions."
        ),
        aio_present=True,
        embed_fn=fake_embed,
    )
    a = await derive_main_entity(**kwargs)
    b = await derive_main_entity(**kwargs)
    assert a.model_dump() == b.model_dump()


# ---------------------------------------------------------------------------
# emq_identical flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emq_identical_flag_set_when_canonical_equals_keyword():
    # The EMQ-identical case lives on the AIO path: the answer's repeated
    # entity is the keyword itself (e.g. a single-term topic).
    answer = (
        "Creatine builds muscle. Creatine improves strength. "
        "Creatine supports recovery. Creatine is well studied."
    )
    result = await derive_main_entity(
        primary_keyword="creatine",
        title="Creatine: A Complete Guide",
        aio_answer_text=answer,
        aio_present=True,
        embed_fn=fake_embed,
    )
    assert result.source == "aio"
    assert result.canonical.lower() == "creatine"
    assert result.emq_identical is True
