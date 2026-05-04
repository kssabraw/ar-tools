"""Step 6.8 — ICP callout LLM judge.

The judge runs after the article is finalized and verifies that the
section designated as the ICP anchor actually surfaced the audience
callout. Tests cover paraphrase tolerance via a fake judge_fn, plus
all the failure modes the verifier must NOT propagate as exceptions.
"""

from __future__ import annotations

import pytest

from models.writer import ArticleSection, BrandVoiceCard
from modules.writer.icp_verification import verify_icp_callout_landed


def _h2(order: int, heading: str, body: str = "") -> ArticleSection:
    return ArticleSection(
        order=order,
        level="H2",
        type="content",
        heading=heading,
        body=body,
        word_count=len(body.split()),
    )


def _article(body: str = "Some prose about returns.") -> list[ArticleSection]:
    return [
        _h2(1, "Pricing", "Pricing prose."),
        _h2(2, "Reduce Returns and Refund Rates", body),
        _h2(3, "Optimize", "Listing prose."),
    ]


def _make_judge(*, landed: bool, evidence: str | None = None, reasoning: str = ""):
    """Test double that returns a fixed JSON payload, recording the
    prompt it received so tests can assert on it."""
    captured: dict = {}

    async def _fn(system: str, user: str, **kw):
        captured["system"] = system
        captured["user"] = user
        captured["kwargs"] = kw
        return {
            "icp_callout_landed": landed,
            "evidence": evidence,
            "reasoning": reasoning,
        }

    _fn.captured = captured  # type: ignore[attr-defined]
    return _fn


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_landed_with_evidence_when_judge_says_yes():
    judge = _make_judge(
        landed=True,
        evidence="brands losing margin to refunds and returns",
        reasoning="The body explicitly names the audience pain.",
    )
    landed, evidence, status = await verify_icp_callout_landed(
        _article("Brands losing margin to refunds and returns are bleeding out."),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="margin erosion from refunds and returns",
        brand_voice_card=BrandVoiceCard(
            audience_pain_points=["margin erosion from refunds and returns"],
            audience_verticals=["Beauty", "Health & Wellness"],
        ),
        judge_fn=judge,
    )
    assert landed is True
    assert evidence == "brands losing margin to refunds and returns"
    assert status == "landed"


@pytest.mark.asyncio
async def test_returns_not_landed_when_judge_says_no():
    judge = _make_judge(landed=False, evidence=None, reasoning="No audience naming.")
    landed, evidence, status = await verify_icp_callout_landed(
        _article("Generic prose with no audience callout."),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="margin erosion from refunds and returns",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["margin erosion"]),
        judge_fn=judge,
    )
    assert landed is False
    assert evidence is None
    assert status == "not_landed"


@pytest.mark.asyncio
async def test_judge_prompt_contains_hook_and_audience_signals():
    judge = _make_judge(landed=True, evidence="x")
    await verify_icp_callout_landed(
        _article("body"),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="margin erosion from refunds and returns",
        brand_voice_card=BrandVoiceCard(
            audience_pain_points=["margin erosion from refunds and returns"],
            audience_verticals=["Beauty", "Health & Wellness"],
        ),
        judge_fn=judge,
    )
    user = judge.captured["user"]  # type: ignore[attr-defined]
    assert "margin erosion from refunds and returns" in user
    assert "Beauty" in user
    assert "Health & Wellness" in user
    assert "SECTION_BODY:" in user


# ---------------------------------------------------------------------------
# Skip / no-op paths — must NOT call the judge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_anchor_text_skips_judge_call():
    called = False

    async def _judge(*a, **kw):
        nonlocal called
        called = True
        return {"icp_callout_landed": True, "evidence": "x", "reasoning": ""}

    landed, evidence, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text=None,
        icp_hook_phrase="some pain",
        brand_voice_card=BrandVoiceCard(),
        judge_fn=_judge,
    )
    assert landed is None
    assert evidence is None
    assert status == "no_anchor"
    assert called is False


@pytest.mark.asyncio
async def test_no_hook_phrase_skips_judge_call():
    called = False

    async def _judge(*a, **kw):
        nonlocal called
        called = True
        return {"icp_callout_landed": True, "evidence": "x"}

    landed, _, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase=None,
        brand_voice_card=BrandVoiceCard(),
        judge_fn=_judge,
    )
    assert landed is None
    assert status == "no_anchor"
    assert called is False


# ---------------------------------------------------------------------------
# Defensive paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anchor_heading_not_in_article_returns_false_with_status():
    """If the anchor section can't be found (heading was rewritten or
    section was dropped), surface as not-landed rather than crashing."""
    judge = _make_judge(landed=True)
    landed, evidence, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Section That Does Not Exist",
        icp_hook_phrase="some pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["some pain"]),
        judge_fn=judge,
    )
    assert landed is False
    assert evidence is None
    assert status == "anchor_not_in_article"


@pytest.mark.asyncio
async def test_empty_anchor_body_returns_false_without_judge_call():
    called = False

    async def _judge(*a, **kw):
        nonlocal called
        called = True
        return {}

    article = [_h2(1, "Returns", "")]
    landed, _, status = await verify_icp_callout_landed(
        article,
        icp_anchor_text="Returns",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=_judge,
    )
    assert landed is False
    assert status == "empty_body"
    assert called is False


@pytest.mark.asyncio
async def test_judge_call_failure_returns_none_unknown():
    """Network / rate-limit / parse errors must return None (unknown).
    Returning False would falsely flag the run."""

    async def _judge(*a, **kw):
        raise RuntimeError("boom: rate limit")

    landed, evidence, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=_judge,
    )
    assert landed is None
    assert evidence is None
    assert status == "judge_error:RuntimeError"


@pytest.mark.asyncio
async def test_judge_payload_not_dict_returns_none():
    async def _judge(*a, **kw):
        return ["unexpected", "list"]

    landed, _, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=_judge,
    )
    assert landed is None
    assert status == "judge_payload_invalid"


@pytest.mark.asyncio
async def test_judge_landed_field_not_bool_returns_none():
    """LLM occasionally returns a string instead of a bool — must not
    silently coerce 'true' / 'false' strings into True/False because
    they could mask real judge failures."""
    async def _judge(*a, **kw):
        return {"icp_callout_landed": "true", "evidence": "x"}

    landed, _, status = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=_judge,
    )
    assert landed is None
    assert status == "judge_payload_invalid"


@pytest.mark.asyncio
async def test_evidence_capped_and_dropped_when_landed_false():
    """When landed=False, evidence should be None even if the judge
    sent something. When landed=True, evidence is capped at the char
    limit so log records and metadata stay bounded."""
    long_evidence = "x" * 1000
    judge = _make_judge(landed=False, evidence=long_evidence)
    _, evidence, _ = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=judge,
    )
    assert evidence is None  # dropped when landed=False

    judge2 = _make_judge(landed=True, evidence=long_evidence)
    _, evidence2, _ = await verify_icp_callout_landed(
        _article(),
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund rate",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund rate"]),
        judge_fn=judge2,
    )
    assert evidence2 is not None
    assert len(evidence2) <= 240


@pytest.mark.asyncio
async def test_anchor_heading_match_is_case_insensitive_and_whitespace_tolerant():
    """Heading matching must tolerate the kind of whitespace / casing
    drift that's been observed between the brief and the final article
    (heading optimizer can re-case, render code can trim)."""
    judge = _make_judge(landed=True, evidence="brands")
    article = [_h2(1, "  REDUCE returns and refund Rates  ", "Brands feeling refund pain.")]
    landed, _, status = await verify_icp_callout_landed(
        article,
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund pain"]),
        judge_fn=judge,
    )
    assert landed is True
    assert status == "landed"


@pytest.mark.asyncio
async def test_long_body_uses_head_plus_tail_truncation():
    """ICP callouts often land in the section's wrap-up paragraph.
    Head-only truncation would clip exactly that prose on long
    sections (5K-9K chars). Verify the head AND tail are both in
    the prompt, with a truncation marker between them."""
    head_marker = "HEAD_PROSE_MARKER"
    tail_marker = "TAIL_PROSE_MARKER"
    middle = "filler " * 1500  # ~10500 chars
    huge_body = head_marker + " " + middle + " " + tail_marker
    judge = _make_judge(landed=True, evidence="x")
    article = [_h2(1, "Returns", huge_body)]
    await verify_icp_callout_landed(
        article,
        icp_anchor_text="Returns",
        icp_hook_phrase="refund pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund pain"]),
        judge_fn=judge,
    )
    user = judge.captured["user"]  # type: ignore[attr-defined]
    body_section = user.split("SECTION_BODY:\n", 1)[1]
    # Both the head and tail markers must survive truncation so the
    # judge sees the prose at both ends of the section.
    assert head_marker in body_section
    assert tail_marker in body_section
    assert "[truncated middle]" in body_section
    # Bounded prompt size — head (2500) + tail (2500) + marker + frame.
    assert len(body_section) < 5500


@pytest.mark.asyncio
async def test_short_body_is_not_truncated():
    """Bodies that fit under the head+tail budget should pass through
    untouched (no truncation marker)."""
    body = "Short prose about returns."
    judge = _make_judge(landed=True, evidence="x")
    await verify_icp_callout_landed(
        [_h2(1, "Returns", body)],
        icp_anchor_text="Returns",
        icp_hook_phrase="refund pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund pain"]),
        judge_fn=judge,
    )
    user = judge.captured["user"]  # type: ignore[attr-defined]
    assert "[truncated middle]" not in user
    assert body in user


@pytest.mark.asyncio
async def test_anchor_heading_match_tolerates_trailing_punctuation():
    """The heading SEO optimizer can append punctuation (e.g. a colon)
    or the brief can author a heading with a question mark; either
    side may have it. Match must succeed when only trailing punctuation
    differs — without this, the validator silently flags
    `anchor_not_in_article` on otherwise-fine articles."""
    judge = _make_judge(landed=True, evidence="audience")
    # Article heading has trailing colon; plan stored bare text.
    article = [_h2(1, "Reduce Returns and Refund Rates:", "Audience prose.")]
    landed, _, status = await verify_icp_callout_landed(
        article,
        icp_anchor_text="Reduce Returns and Refund Rates",
        icp_hook_phrase="refund pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund pain"]),
        judge_fn=judge,
    )
    assert landed is True
    assert status == "landed"

    # Reverse: plan has trailing punctuation, article doesn't.
    article2 = [_h2(1, "How to Reduce Returns", "Audience prose.")]
    landed2, _, status2 = await verify_icp_callout_landed(
        article2,
        icp_anchor_text="How to Reduce Returns?",
        icp_hook_phrase="refund pain",
        brand_voice_card=BrandVoiceCard(audience_pain_points=["refund pain"]),
        judge_fn=judge,
    )
    assert landed2 is True
    assert status2 == "landed"
