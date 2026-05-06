"""Tests for Brief Generator v2.0 Step 10 - FAQ generation.

Mocks the LLM and embedder via injected functions; no real API calls.
"""

from __future__ import annotations

import math

import pytest

from modules.brief.faqs import (
    DEFAULT_MIN_FAQ_SCORE,
    FAQCandidate,
    MAX_FAQS,
    MIN_FAQS_FALLBACK,
    extract_question_sentences,
    llm_concern_extraction,
    regex_faq_pool,
    score_faqs,
    select_faqs,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


def _make_embed(table: dict[str, list[float]]):
    """Build an async embedder that looks up vectors by exact text."""
    async def _embed(texts: list[str]) -> list[list[float]]:
        return [_normalize(list(table[t])) for t in texts]
    return _embed


# ----------------------------------------------------------------------
# extract_question_sentences (regex)
# ----------------------------------------------------------------------

def test_extract_question_filters_by_word_count():
    text = (
        "Why? Too short. "
        "What is TikTok Shop and how does it work for sellers? "
        "This is " + "x " * 30 + "? "  # too long → 30+ words
    )
    out = extract_question_sentences(text)
    # Only the middle question fits the 5-25 word window
    assert any("What is TikTok Shop" in q for q in out)
    assert "Why?" not in out


# ----------------------------------------------------------------------
# regex_faq_pool - Source A + C dedup
# ----------------------------------------------------------------------

def test_paa_questions_are_first_class_candidates():
    pool = regex_faq_pool(
        paa_questions=["What is TikTok Shop?", "How do I set it up?"],
        reddit_titles=[],
        reddit_comments=[],
    )
    assert {c.source for c in pool} == {"paa"}
    assert len(pool) == 2


def test_reddit_titles_extract_questions():
    pool = regex_faq_pool(
        paa_questions=[],
        reddit_titles=["Has anyone tried TikTok Shop in Canada yet?"],
        reddit_comments=[],
    )
    assert len(pool) == 1
    assert pool[0].source == "reddit"
    assert pool[0].upvotes == 10  # default for Reddit pool


def test_reddit_dedup_against_paa():
    """Same normalized question in both PAA and Reddit → single PAA candidate."""
    pool = regex_faq_pool(
        paa_questions=["What is TikTok Shop?"],
        reddit_titles=["What is TikTok Shop"],
        reddit_comments=[],
    )
    assert len(pool) == 1
    assert pool[0].source == "paa"


def test_persona_gap_questions_become_candidates():
    pool = regex_faq_pool(
        paa_questions=[],
        reddit_titles=[],
        reddit_comments=[],
        persona_gap_questions=[
            "Does TikTok Shop charge listing fees?",
            "Can I sell digital products on TikTok Shop?",
        ],
    )
    assert len(pool) == 2
    assert all(c.source == "persona_gap" for c in pool)


def test_persona_gap_dedups_against_paa_paraphrase():
    """A persona gap question already covered by PAA should not duplicate."""
    pool = regex_faq_pool(
        paa_questions=["What is TikTok Shop?"],
        reddit_titles=[],
        reddit_comments=[],
        persona_gap_questions=["What is TikTok Shop"],  # same after norm
    )
    assert len(pool) == 1
    assert pool[0].source == "paa"


def test_persona_gap_question_without_question_mark_is_normalized():
    """Step 6 should output trailing '?' but be defensive."""
    pool = regex_faq_pool(
        paa_questions=[],
        reddit_titles=[],
        reddit_comments=[],
        persona_gap_questions=["Will TikTok Shop work for B2B"],
    )
    assert len(pool) == 1
    assert pool[0].question.endswith("?")


# ----------------------------------------------------------------------
# llm_concern_extraction (Source B) - injected LLM
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_concern_extraction_returns_candidates():
    async def _mock(system, user, **kw):
        return {"questions": [
            "How do I handle returns on TikTok Shop?",
            "What payment methods does TikTok Shop support?",
        ]}
    out = await llm_concern_extraction("reddit text", llm_json_fn=_mock)
    assert len(out) == 2
    assert all(c.source == "llm_extracted" for c in out)


@pytest.mark.asyncio
async def test_llm_concern_extraction_filters_short_long():
    async def _mock(system, user, **kw):
        return {"questions": [
            "Too short?",  # 2 words → dropped
            "How exactly do I configure shipping for TikTok Shop?",  # 8 words ✓
            "x " * 35 + "?",  # too long → dropped
        ]}
    out = await llm_concern_extraction("text", llm_json_fn=_mock)
    assert len(out) == 1
    assert "configure shipping" in out[0].question


@pytest.mark.asyncio
async def test_llm_concern_extraction_empty_input_no_call():
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("must not call LLM with empty input")

    out = await llm_concern_extraction("", llm_json_fn=boom)
    assert out == []
    assert called is False


@pytest.mark.asyncio
async def test_llm_concern_extraction_handles_llm_exception():
    async def boom(*a, **k):
        raise RuntimeError("upstream failed")

    out = await llm_concern_extraction("real reddit text", llm_json_fn=boom)
    # Per PRD: FAQ extraction never aborts the run
    assert out == []


@pytest.mark.asyncio
async def test_llm_concern_extraction_handles_malformed_payload():
    async def _mock(system, user, **kw):
        return {"not_questions": []}  # wrong key

    out = await llm_concern_extraction("text", llm_json_fn=_mock)
    assert out == []


# ----------------------------------------------------------------------
# score_faqs - uses TITLE embedding (v2.0 change from seed)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_uses_title_embedding_not_seed():
    """faq_score's semantic_relevance is cosine to title embedding."""
    title_emb = _normalize([1.0, 0.0, 0.0])
    embed_table = {
        "What is TikTok Shop?": [1.0, 0.0, 0.0],     # exact match → cos 1.0
        "Cooking recipes?":     [0.0, 1.0, 0.0],     # orthogonal → cos 0
    }
    cands = [
        FAQCandidate(question="What is TikTok Shop?", source="paa"),
        FAQCandidate(question="Cooking recipes?", source="paa"),
    ]
    scored = await score_faqs(
        cands, title_emb, heading_texts_norm=set(),
        embed_fn=_make_embed(embed_table),
    )
    by_q = {c.question: c for c in scored}
    assert by_q["What is TikTok Shop?"].semantic_score == pytest.approx(1.0)
    assert by_q["Cooking recipes?"].semantic_score == pytest.approx(0.0, abs=1e-9)


@pytest.mark.asyncio
async def test_score_persona_gap_source_signal_is_0_6():
    title_emb = _normalize([1.0, 0.0])
    embed_table = {"q?": [1.0, 0.0]}
    cands = [FAQCandidate(question="q?", source="persona_gap")]
    scored = await score_faqs(
        cands, title_emb, heading_texts_norm=set(),
        embed_fn=_make_embed(embed_table),
    )
    # source_signal=0.6, semantic=1.0, novelty=1.0
    # → 0.4*0.6 + 0.4*1.0 + 0.2*1.0 = 0.24 + 0.40 + 0.20 = 0.84
    assert scored[0].faq_score == pytest.approx(0.84)


@pytest.mark.asyncio
async def test_score_paa_source_signal_is_1_0():
    title_emb = _normalize([1.0, 0.0])
    embed_table = {"q?": [1.0, 0.0]}
    cands = [FAQCandidate(question="q?", source="paa")]
    scored = await score_faqs(
        cands, title_emb, heading_texts_norm=set(),
        embed_fn=_make_embed(embed_table),
    )
    # source=1.0, semantic=1.0, novelty=1.0 → 0.4 + 0.4 + 0.2 = 1.0
    assert scored[0].faq_score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_score_reddit_tiers_by_upvotes():
    title_emb = _normalize([1.0, 0.0])
    embed_table = {
        "high?": [1.0, 0.0],
        "mid?": [1.0, 0.0],
        "low?": [1.0, 0.0],
    }
    cands = [
        FAQCandidate(question="high?", source="reddit", upvotes=80),
        FAQCandidate(question="mid?", source="reddit", upvotes=15),
        FAQCandidate(question="low?", source="reddit", upvotes=2),
    ]
    scored = await score_faqs(
        cands, title_emb, heading_texts_norm=set(),
        embed_fn=_make_embed(embed_table),
    )
    sigs = {c.question: 0.4 * c.faq_score for c in scored}  # rough sort
    # high (0.9) > mid (0.6) > low (0.3) on the source-signal component
    assert scored[0].faq_score > scored[1].faq_score
    assert scored[1].faq_score > scored[2].faq_score


@pytest.mark.asyncio
async def test_score_novelty_zero_when_question_already_in_headings():
    title_emb = _normalize([1.0, 0.0])
    embed_table = {"What is TikTok Shop?": [1.0, 0.0]}
    cands = [FAQCandidate(question="What is TikTok Shop?", source="paa")]
    scored = await score_faqs(
        cands, title_emb,
        heading_texts_norm={"what is tiktok shop"},  # normalized form
        embed_fn=_make_embed(embed_table),
    )
    assert scored[0].novelty_bonus == 0.0
    # source=1.0, semantic=1.0, novelty=0.0 → 0.4 + 0.4 + 0 = 0.8
    assert scored[0].faq_score == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_score_empty_candidates_returns_empty():
    out = await score_faqs([], [1.0, 0.0], set())
    assert out == []


# ----------------------------------------------------------------------
# select_faqs - top-5 with min-score, fallback to top-3
# ----------------------------------------------------------------------

def _scored(question: str, source: str, score: float) -> FAQCandidate:
    c = FAQCandidate(question=question, source=source)  # type: ignore[arg-type]
    c.faq_score = score
    return c


def test_select_returns_top_five_above_threshold():
    cands = [_scored(f"q{i}?", "paa", 0.5 + i * 0.05) for i in range(8)]
    out = select_faqs(cands, min_score=DEFAULT_MIN_FAQ_SCORE)
    assert len(out) == MAX_FAQS
    # Highest-score first
    assert out[0].faq_score >= out[-1].faq_score


def test_select_falls_back_to_top_three_when_under_threshold():
    """If <3 candidates pass threshold, fall back to ranked top 3."""
    cands = [
        _scored("q1?", "paa", 0.55),  # pass
        _scored("q2?", "paa", 0.40),  # fail
        _scored("q3?", "paa", 0.35),  # fail
        _scored("q4?", "paa", 0.30),  # fail
    ]
    out = select_faqs(cands, min_score=0.5)
    # Only one passes → fallback to top 3 by score
    assert len(out) == 3
    scores = [item.faq_score for item in out]
    assert scores == sorted(scores, reverse=True)


def test_select_returns_three_when_pool_smaller_than_max():
    cands = [_scored(f"q{i}?", "paa", 0.6) for i in range(3)]
    out = select_faqs(cands, min_score=0.5)
    assert len(out) == 3


def test_select_empty_returns_empty():
    assert select_faqs([], min_score=0.5) == []


def test_select_returns_full_pool_when_smaller_than_min_fallback():
    """1 candidate, all below threshold → returns the 1 (top 3 cap)."""
    cands = [_scored("q?", "paa", 0.10)]
    out = select_faqs(cands, min_score=0.5)
    assert len(out) == 1


def test_select_rounds_score_in_output():
    cands = [_scored("q?", "paa", 0.66666666)]
    out = select_faqs(cands, min_score=0.5)
    assert out[0].faq_score == 0.6667


# ---------------------------------------------------------------------------
# Phase 2 / PRD v2.2 - Blended semantic_score (cosine-to-title +
# cosine-to-intent-profile)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_faqs_blends_cosine_when_intent_profile_supplied():
    """Phase 2: when intent_profile_embedding is supplied, semantic_score
    is the 50/50 weighted average of cosine-to-title and cosine-to-
    intent-profile."""
    import math
    from modules.brief.faqs import FAQCandidate, score_faqs

    def _unit(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    # Title axis = x; intent-profile axis = y. The FAQ has cosine 1.0
    # to title and cosine 0.0 to intent-profile → blended = 0.5.
    title_emb = _unit([1.0, 0.0])
    intent_emb = _unit([0.0, 1.0])

    async def fake_embed(texts):
        # All FAQ text aligns with the title axis (cos=1 to title,
        # cos=0 to intent_profile).
        return [_unit([1.0, 0.0]) for _ in texts]

    cands = [FAQCandidate(question="q1", source="paa")]
    await score_faqs(
        cands, title_emb, set(), embed_fn=fake_embed,
        intent_profile_embedding=intent_emb,
    )
    assert cands[0].title_cosine == pytest.approx(1.0, abs=1e-6)
    assert cands[0].intent_profile_cosine == pytest.approx(0.0, abs=1e-6)
    assert cands[0].semantic_score == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_score_faqs_falls_back_to_title_only_when_no_intent_profile():
    """Without intent_profile_embedding, semantic_score is cosine-to-
    title only (v2.0 / v2.1 backward compatibility)."""
    import math
    from modules.brief.faqs import FAQCandidate, score_faqs

    def _unit(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    title_emb = _unit([1.0, 0.0])

    async def fake_embed(texts):
        return [_unit([1.0, 0.0]) for _ in texts]

    cands = [FAQCandidate(question="q1", source="paa")]
    await score_faqs(cands, title_emb, set(), embed_fn=fake_embed)
    # No intent_profile → semantic_score == title_cosine
    assert cands[0].title_cosine == pytest.approx(1.0, abs=1e-6)
    assert cands[0].intent_profile_cosine == 0.0
    assert cands[0].semantic_score == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_score_faqs_accepts_pre_computed_embeddings():
    """Phase 2: callers can pass pre-computed candidate_embeddings to
    avoid a second embedding API call after the FAQ intent gate
    already embedded them."""
    import math
    from modules.brief.faqs import FAQCandidate, score_faqs

    def _unit(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    title_emb = _unit([1.0, 0.0])
    pre = [_unit([1.0, 0.0]), _unit([0.5, 0.5])]
    cands = [
        FAQCandidate(question="q1", source="paa"),
        FAQCandidate(question="q2", source="paa"),
    ]

    embed_calls = {"n": 0}

    async def watching_embed(texts):
        embed_calls["n"] += 1
        return [_unit([0.0, 1.0]) for _ in texts]

    await score_faqs(
        cands, title_emb, set(),
        embed_fn=watching_embed,
        candidate_embeddings=pre,
    )
    # The fallback embedder must NOT have been called when
    # candidate_embeddings is supplied.
    assert embed_calls["n"] == 0
    # Title cosines reflect the PRE-computed vectors, not the embedder.
    assert cands[0].title_cosine == pytest.approx(1.0, abs=1e-6)


def test_select_faqs_surfaces_intent_role_on_output():
    """Phase 2: when a FAQCandidate carries `intent_role` (set by Step
    10.5), the resulting FAQItem surfaces it verbatim."""
    from modules.brief.faqs import FAQCandidate, select_faqs

    cands = [
        FAQCandidate(question=f"q{i}", source="paa", faq_score=0.9 - i * 0.01)
        for i in range(3)
    ]
    cands[0].intent_role = "matches_primary_intent"
    cands[1].intent_role = "adjacent_intent"
    # cands[2].intent_role left as None
    items = select_faqs(cands)
    by_q = {it.question: it for it in items}
    assert by_q["q0"].intent_role == "matches_primary_intent"
    assert by_q["q1"].intent_role == "adjacent_intent"
    assert by_q["q2"].intent_role is None
