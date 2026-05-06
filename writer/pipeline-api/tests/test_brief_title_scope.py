"""Unit tests for Brief Generator v2.0 Step 3.5 - title + scope generation.

Mocks the LLM via injected `llm_json_fn`; no real Claude calls.
"""

from __future__ import annotations

import pytest

from modules.brief.pipeline import BriefError
from modules.brief.title_scope import (
    BANNED_TITLE_PHRASES,
    MAX_TITLE_LEN,
    REQUIRED_SCOPE_PHRASE,
    TitleScopeOutput,
    generate_title_and_scope,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_llm_mock(*responses):
    """Build a mock llm_json_fn that returns each of the given responses
    in turn. If a response is an Exception, it's raised."""
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


VALID_PAYLOAD = {
    "title": "What TikTok Shop Is and How It Works in 2026",
    "scope_statement": (
        "Defines TikTok Shop, explains how the system functions for both "
        "sellers and buyers, and orients readers to major components. "
        "Does not cover advanced seller tactics, algorithm optimization, "
        "or inventory management decisions."
    ),
    "title_rationale": (
        "Top 20 SERP titles converge on definitional framing; "
        "featured snippet present indicates Google has settled on a "
        "canonical definition format."
    ),
}


_INPUTS = dict(
    seed_keyword="what is tiktok shop",
    intent_type="informational",
    serp_titles=["What is TikTok Shop?", "TikTok Shop Explained"],
    serp_h1s=["TikTok Shop", "Welcome to TikTok Shop"],
    meta_descriptions=["TikTok Shop is...", "Learn about TikTok Shop..."],
    fanout_response_bodies=["AI explanation 1", "AI explanation 2"],
)


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_attempt_success_returns_validated_output():
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(VALID_PAYLOAD),
    )
    assert isinstance(res, TitleScopeOutput)
    assert res.title.startswith("What TikTok Shop Is")
    assert REQUIRED_SCOPE_PHRASE in res.scope_statement.lower()
    assert res.title_rationale  # non-empty


@pytest.mark.asyncio
async def test_first_attempt_uses_high_temperature_for_variation():
    """Title is the source of truth for the writer's title/h1 (writer
    consumes them verbatim). On regenerate the brief cache is bypassed,
    so all variation has to come from THIS LLM call. First attempt must
    use a non-trivial temperature (≥0.5) to produce meaningfully
    different titles across regenerations of the same keyword."""
    captured: list[float] = []

    async def _capturing_mock(system, user, **kw):
        captured.append(kw.get("temperature", 0.0))
        return VALID_PAYLOAD

    await generate_title_and_scope(**_INPUTS, llm_json_fn=_capturing_mock)
    assert captured, "expected at least one LLM call"
    assert captured[0] >= 0.5, (
        f"first-attempt temperature {captured[0]} too low for "
        "regeneration variation"
    )


@pytest.mark.asyncio
async def test_retry_uses_low_temperature_for_structure():
    """When the first attempt returns malformed output, retry drops
    temperature low so the structured JSON is more likely to validate."""
    captured: list[float] = []

    async def _capturing_mock(system, user, **kw):
        captured.append(kw.get("temperature", 0.0))
        # First call returns bad payload (missing scope phrase),
        # second call returns valid.
        if len(captured) == 1:
            return dict(VALID_PAYLOAD, scope_statement="totally off-scope text")
        return VALID_PAYLOAD

    await generate_title_and_scope(**_INPUTS, llm_json_fn=_capturing_mock)
    assert len(captured) == 2
    assert captured[1] < captured[0], (
        "retry temperature must be lower than first-attempt temperature"
    )
    assert captured[1] <= 0.2


@pytest.mark.asyncio
async def test_rationale_truncated_when_overlong():
    payload = dict(VALID_PAYLOAD, title_rationale="x" * 500)
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    # Truncated to 300, not rejected
    assert len(res.title_rationale) == 300


@pytest.mark.asyncio
async def test_rationale_can_be_empty():
    payload = dict(VALID_PAYLOAD, title_rationale="")
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    assert res.title_rationale == ""


# ----------------------------------------------------------------------
# Validation failures → retry → success
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_missing_does_not_cover_clause():
    bad = dict(VALID_PAYLOAD, scope_statement="Defines TikTok Shop. End.")
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
    )
    assert REQUIRED_SCOPE_PHRASE in res.scope_statement.lower()


@pytest.mark.asyncio
async def test_retry_on_overlong_title():
    bad = dict(VALID_PAYLOAD, title="x" * (MAX_TITLE_LEN + 1))
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
    )
    assert len(res.title) <= MAX_TITLE_LEN


@pytest.mark.asyncio
async def test_retry_on_banned_phrase():
    bad = dict(VALID_PAYLOAD, title="The Ultimate Guide to TikTok Shop")
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
    )
    assert "ultimate guide" not in res.title.lower()


@pytest.mark.asyncio
async def test_retry_on_empty_title():
    bad = dict(VALID_PAYLOAD, title="")
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
    )
    assert res.title


@pytest.mark.asyncio
async def test_retry_on_overlong_scope():
    bad = dict(VALID_PAYLOAD, scope_statement="x" * 501 + " does not cover y")
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
    )
    assert len(res.scope_statement) <= 500


@pytest.mark.asyncio
async def test_retry_on_non_dict_payload():
    res = await generate_title_and_scope(
        **_INPUTS, llm_json_fn=_make_llm_mock("not a dict", VALID_PAYLOAD),
    )
    assert res.title


@pytest.mark.asyncio
async def test_retry_on_llm_exception():
    res = await generate_title_and_scope(
        **_INPUTS,
        llm_json_fn=_make_llm_mock(RuntimeError("boom"), VALID_PAYLOAD),
    )
    assert res.title


# ----------------------------------------------------------------------
# Abort path: two failures → BriefError
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aborts_after_two_validation_failures():
    bad1 = dict(VALID_PAYLOAD, scope_statement="no marker")
    bad2 = dict(VALID_PAYLOAD, title="x" * 200)
    with pytest.raises(BriefError) as ei:
        await generate_title_and_scope(
            **_INPUTS, llm_json_fn=_make_llm_mock(bad1, bad2),
        )
    assert ei.value.code == "title_generation_failed"
    assert "title_too_long" in ei.value.message


@pytest.mark.asyncio
async def test_aborts_after_two_llm_exceptions():
    with pytest.raises(BriefError) as ei:
        await generate_title_and_scope(
            **_INPUTS,
            llm_json_fn=_make_llm_mock(
                RuntimeError("first failure"),
                RuntimeError("second failure"),
            ),
        )
    assert ei.value.code == "title_generation_failed"


@pytest.mark.asyncio
async def test_banned_phrase_check_is_case_insensitive():
    """Verify each banned phrase triggers rejection regardless of casing."""
    for banned in BANNED_TITLE_PHRASES:
        bad_title = banned.upper().strip() + " to TikTok Shop"
        bad = dict(VALID_PAYLOAD, title=bad_title[:MAX_TITLE_LEN])
        with pytest.raises(BriefError):
            # Both attempts return the same banned title → abort
            await generate_title_and_scope(
                **_INPUTS, llm_json_fn=_make_llm_mock(bad, bad),
            )


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logs_success(caplog):
    with caplog.at_level("INFO", logger="modules.brief.title_scope"):
        await generate_title_and_scope(
            **_INPUTS, llm_json_fn=_make_llm_mock(VALID_PAYLOAD),
        )
    assert any(r.message == "brief.title_scope.generated" for r in caplog.records)


@pytest.mark.asyncio
async def test_logs_validation_warning_on_retry(caplog):
    bad = dict(VALID_PAYLOAD, scope_statement="no marker here")
    with caplog.at_level("WARNING", logger="modules.brief.title_scope"):
        await generate_title_and_scope(
            **_INPUTS, llm_json_fn=_make_llm_mock(bad, VALID_PAYLOAD),
        )
    assert any(r.message == "brief.title_scope.invalid" for r in caplog.records)
