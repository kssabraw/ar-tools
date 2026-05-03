"""Step 10.5 — FAQ Intent Gate (PRD v2.2 / Phase 2)."""

from __future__ import annotations

import math

import pytest

from modules.brief.faq_intent_gate import (
    INTENT_FLOOR,
    apply_cosine_floor,
    apply_faq_intent_gate,
    build_intent_profile_text,
    embed_intent_profile,
)
from modules.brief.faqs import FAQCandidate


def _unit(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _faq(
    question: str,
    *,
    source: str = "paa",
    faq_score: float = 0.6,
) -> FAQCandidate:
    return FAQCandidate(question=question, source=source, faq_score=faq_score)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_intent_profile_text
# ---------------------------------------------------------------------------


def test_intent_profile_text_includes_persona_goal():
    text = build_intent_profile_text(
        intent_type="how-to",
        title="How to Increase ROI for Your TikTok Shop",
        scope_statement="Covers seller-side ROI tactics. Does not cover creator monetization.",
        persona_primary_goal="Decide whether to invest more in TikTok Shop ads.",
    )
    assert "how-to" in text
    assert "TikTok Shop" in text
    assert "creator monetization" in text
    assert "TikTok Shop ads" in text


def test_intent_profile_text_omits_empty_persona():
    text = build_intent_profile_text(
        intent_type="informational",
        title="What Is TikTok Shop",
        scope_statement="Defines TikTok Shop. Does not cover algorithm tuning.",
        persona_primary_goal="",
    )
    assert "Reader's primary goal" not in text


# ---------------------------------------------------------------------------
# embed_intent_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_intent_profile_returns_vector_on_success():
    async def fake_embed(texts):
        return [_unit([1.0, 0.0, 0.0])]
    vec = await embed_intent_profile("intent profile", embed_fn=fake_embed)
    assert vec == _unit([1.0, 0.0, 0.0])


@pytest.mark.asyncio
async def test_embed_intent_profile_returns_empty_on_failure():
    async def boom(texts):
        raise RuntimeError("embed outage")
    vec = await embed_intent_profile("intent profile", embed_fn=boom)
    assert vec == []


@pytest.mark.asyncio
async def test_embed_intent_profile_returns_empty_for_blank():
    async def fake_embed(texts):
        raise AssertionError("should not be called")
    vec = await embed_intent_profile("   ", embed_fn=fake_embed)
    assert vec == []


# ---------------------------------------------------------------------------
# apply_cosine_floor
# ---------------------------------------------------------------------------


def test_cosine_floor_drops_low_alignment():
    profile = _unit([1.0, 0.0, 0.0])
    candidates = [_faq("aligned"), _faq("misaligned")]
    embeddings = [_unit([1.0, 0.05, 0.0]), _unit([0.0, 1.0, 0.0])]
    survivors, rejected = apply_cosine_floor(
        candidates, profile, embeddings, floor=INTENT_FLOOR,
    )
    assert [c.question for c in survivors] == ["aligned"]
    assert [c.question for c in rejected] == ["misaligned"]


def test_cosine_floor_keeps_all_when_above_threshold():
    profile = _unit([1.0, 0.0, 0.0])
    candidates = [_faq("a"), _faq("b")]
    embeddings = [_unit([1.0, 0.05, 0.0]), _unit([0.99, 0.1, 0.0])]
    survivors, rejected = apply_cosine_floor(
        candidates, profile, embeddings, floor=0.5,
    )
    assert len(survivors) == 2
    assert rejected == []


# ---------------------------------------------------------------------------
# apply_faq_intent_gate — full flow
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_embed_factory():
    """Build a fake embedder that returns a vector aligned with one of
    two axes based on whether the text mentions 'creator' or 'seller'.
    The intent profile is anchored on the SELLER axis so creator FAQs
    fail the cosine floor.
    """
    def factory(*, threshold: float = 0.55):
        async def embed(texts):
            vectors = []
            for t in texts:
                low = t.lower()
                if "seller" in low or "roi" in low or "shop" in low:
                    vectors.append(_unit([1.0, 0.05, 0.0]))
                elif "creator" in low or "monetiz" in low:
                    vectors.append(_unit([0.0, 1.0, 0.0]))
                else:
                    # Neutral — sits between the axes
                    vectors.append(_unit([0.7, 0.7, 0.0]))
            return vectors
        return embed
    return factory


@pytest.mark.asyncio
async def test_intent_gate_drops_creator_faqs_for_seller_article(fake_embed_factory):
    """Audit failure case: seller-ROI article, creator-monetization FAQs
    in the candidate pool. Cosine floor + LLM filter should drop them."""
    candidates = [
        _faq("How long does TikTok Shop take to approve sellers?"),
        _faq("What payment methods does TikTok Shop support for sellers?"),
        _faq("How do creators monetize on TikTok?"),
        _faq("What are creator earnings caps?"),
    ]

    async def fake_llm(system, user, **kwargs):
        # Mark seller FAQs as primary; creator FAQs as different_audience.
        # Note: by the time we get here, only survivors of the cosine
        # floor reach us. The fixture's embedder pushes creator FAQs
        # below the 0.55 floor, so they shouldn't reach the LLM at all.
        # If the embedder is loose, the LLM still drops them.
        import json as _json
        marker = "FAQs to verify (JSON):\n"
        if marker in user:
            payload = user.split(marker, 1)[1].strip()
            end = payload.rfind("]")
            if end != -1:
                payload = payload[: end + 1]
            items = _json.loads(payload)
            verifications = []
            for item in items:
                ql = item["question"].lower()
                role = (
                    "different_audience" if "creator" in ql or "monetiz" in ql
                    else "matches_primary_intent"
                )
                verifications.append({
                    "faq_id": item["faq_id"],
                    "intent_role": role,
                    "reasoning": "test",
                })
            return {"verifications": verifications}
        return {"verifications": []}

    result = await apply_faq_intent_gate(
        candidates,
        intent_type="how-to",
        title="How to Increase ROI for Your TikTok Shop",
        scope_statement="Covers seller-side ROI. Does not cover creator monetization.",
        persona_primary_goal="Optimize seller ROI on TikTok Shop.",
        embed_fn=fake_embed_factory(),
        llm_json_fn=fake_llm,
    )

    # All creator FAQs should be rejected (floor + LLM combined)
    kept_questions = [c.question for c in result.kept]
    assert all("creator" not in q.lower() for q in kept_questions)
    assert all("monetiz" not in q.lower() for q in kept_questions)
    # Seller FAQs survive as primary
    assert any("seller" in q.lower() for q in kept_questions)
    for c in result.kept:
        if c.intent_role:
            assert c.intent_role in ("matches_primary_intent", "adjacent_intent")
    # At least one creator FAQ in rejected
    rejected_questions = [c.question for c in result.rejected]
    assert any("creator" in q.lower() or "monetiz" in q.lower()
               for q in rejected_questions)


@pytest.mark.asyncio
async def test_intent_gate_relaxation_when_few_primary(fake_embed_factory):
    """When fewer than 3 matches_primary_intent survive, top up with
    adjacent_intent until reaching 3. Verify relaxation flag is set."""
    candidates = [
        _faq("How long to approve TikTok Shop seller?"),
        # Two adjacent-but-on-topic candidates
        _faq("What is TikTok Shop?"),
        _faq("TikTok Shop history"),
    ]

    async def fake_llm(system, user, **kwargs):
        import json as _json
        marker = "FAQs to verify (JSON):\n"
        payload = user.split(marker, 1)[1].strip()
        end = payload.rfind("]")
        if end != -1:
            payload = payload[: end + 1]
        items = _json.loads(payload)
        verifications = []
        for i, item in enumerate(items):
            # Only the first FAQ is primary; rest are adjacent.
            role = "matches_primary_intent" if i == 0 else "adjacent_intent"
            verifications.append({
                "faq_id": item["faq_id"],
                "intent_role": role,
                "reasoning": "test",
            })
        return {"verifications": verifications}

    result = await apply_faq_intent_gate(
        candidates,
        intent_type="how-to",
        title="How to Sell on TikTok Shop",
        scope_statement="Covers seller setup.",
        persona_primary_goal="Set up a TikTok Shop seller account.",
        embed_fn=fake_embed_factory(),
        llm_json_fn=fake_llm,
    )

    assert result.relaxation_applied is True
    assert len(result.kept) >= 3
    # Primary candidate should be in kept
    assert any(c.intent_role == "matches_primary_intent" for c in result.kept)
    # Adjacent fallbacks should also be in kept
    assert any(c.intent_role == "adjacent_intent" for c in result.kept)


@pytest.mark.asyncio
async def test_intent_gate_falls_back_when_embed_fails():
    """If the intent profile fails to embed, skip the gate entirely
    and pass all candidates through with fallback flag set."""
    candidates = [_faq("a"), _faq("b")]

    async def boom(texts):
        raise RuntimeError("embed outage")

    result = await apply_faq_intent_gate(
        candidates,
        intent_type="informational",
        title="Title",
        scope_statement="Scope. Does not cover X.",
        persona_primary_goal="",
        embed_fn=boom,
        llm_json_fn=lambda *a, **k: {},  # type: ignore[arg-type]
    )
    assert result.fallback_embed_applied is True
    assert len(result.kept) == len(candidates)
    assert result.floor_rejected_count == 0
    assert result.llm_rejected_count == 0


@pytest.mark.asyncio
async def test_intent_gate_falls_back_when_llm_fails(fake_embed_factory):
    """LLM unavailable → keep cosine-floor survivors; mark each as
    matches_primary_intent."""
    candidates = [
        _faq("How long to approve TikTok Shop seller?"),
        _faq("What payment methods for TikTok Shop sellers?"),
    ]

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM outage")

    result = await apply_faq_intent_gate(
        candidates,
        intent_type="how-to",
        title="Title",
        scope_statement="Scope. Does not cover X.",
        persona_primary_goal="seller goal",
        embed_fn=fake_embed_factory(),
        llm_json_fn=boom,
    )
    assert result.fallback_llm_applied is True
    assert len(result.kept) == len(candidates)
    for c in result.kept:
        assert c.intent_role == "matches_primary_intent"


@pytest.mark.asyncio
async def test_empty_candidates_returns_empty_noop():
    async def fake_llm(*args, **kwargs):
        raise AssertionError("should not call LLM")
    result = await apply_faq_intent_gate(
        [],
        intent_type="how-to",
        title="t",
        scope_statement="s",
        persona_primary_goal="g",
        llm_json_fn=fake_llm,
    )
    assert result.kept == []
    assert result.rejected == []
