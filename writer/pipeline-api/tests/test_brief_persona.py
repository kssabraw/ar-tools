"""Unit tests for Brief Generator v2.0 Step 6 — persona generation.

Mocks the LLM via injected llm_json_fn; no real Claude calls.
"""

from __future__ import annotations

import pytest

from modules.brief.persona import (
    MAX_GAP_QUESTIONS,
    MIN_GAP_QUESTIONS,
    PersonaResult,
    generate_persona,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_llm_mock(*responses):
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


def _valid_payload(num_questions: int = 6) -> dict:
    return {
        "persona": {
            "description": "A small business owner curious about TikTok Shop.",
            "background_assumptions": [
                "Knows what TikTok is",
                "Has a basic understanding of e-commerce",
                "Is not a TikTok creator",
            ],
            "primary_goal": "Decide whether TikTok Shop is worth setting up.",
        },
        "gap_questions": [
            {"question": f"Q{i}?", "rationale": f"R{i}"}
            for i in range(num_questions)
        ],
    }


_INPUTS = dict(
    seed_keyword="what is tiktok shop",
    intent_type="informational",
    title="What TikTok Shop Is and How It Works in 2026",
    scope_statement=(
        "Defines TikTok Shop and explains how it works. "
        "Does not cover advanced seller tactics or algorithm optimization."
    ),
    serp_h1s=["TikTok Shop", "TikTok Shop Explained"],
    meta_descriptions=["TikTok Shop is a feature..."],
    candidate_headings=["What is TikTok Shop", "How does TikTok Shop work"],
)


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_attempt_success():
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(_valid_payload(7)),
    )
    assert isinstance(res, PersonaResult)
    assert len(res.gap_questions) == 7
    assert res.description.startswith("A small business owner")
    assert res.primary_goal.endswith("setting up.")
    assert len(res.background_assumptions) == 3


@pytest.mark.asyncio
async def test_minimum_gap_questions_count_accepted():
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(_valid_payload(MIN_GAP_QUESTIONS)),
    )
    assert len(res.gap_questions) == MIN_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_maximum_gap_questions_count_accepted():
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(_valid_payload(MAX_GAP_QUESTIONS)),
    )
    assert len(res.gap_questions) == MAX_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_background_assumptions_truncated_to_max_5():
    payload = _valid_payload()
    payload["persona"]["background_assumptions"] = [f"a{i}" for i in range(10)]
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    assert len(res.background_assumptions) == 5


@pytest.mark.asyncio
async def test_overlong_strings_truncated():
    payload = _valid_payload()
    payload["persona"]["description"] = "x" * 1000
    payload["persona"]["primary_goal"] = "x" * 1000
    payload["gap_questions"][0]["rationale"] = "x" * 1000
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    assert len(res.description) <= 300
    assert len(res.primary_goal) <= 200
    assert len(res.gap_questions[0].rationale) <= 200


@pytest.mark.asyncio
async def test_drops_invalid_gap_question_entries():
    payload = _valid_payload()
    payload["gap_questions"] = [
        {"question": "Real?", "rationale": "yes"},
        "not a dict",  # dropped
        {"question": "", "rationale": "empty"},  # dropped (empty question)
        {"rationale": "no question"},  # dropped (missing question)
        {"question": "Also real?", "rationale": "yes"},
        {"question": "Third?", "rationale": "yes"},
        {"question": "Fourth?", "rationale": "yes"},
        {"question": "Fifth?", "rationale": "yes"},
    ]
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    # 5 valid entries → meets minimum
    assert len(res.gap_questions) == 5
    assert all(q.question for q in res.gap_questions)


# ----------------------------------------------------------------------
# Validation failures → retry → success
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_too_few_questions():
    bad = _valid_payload(num_questions=3)  # below MIN
    good = _valid_payload(num_questions=6)
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, good),
    )
    assert len(res.gap_questions) == 6


@pytest.mark.asyncio
async def test_retry_on_too_many_questions():
    bad = _valid_payload(num_questions=15)  # above MAX
    good = _valid_payload(num_questions=8)
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, good),
    )
    assert len(res.gap_questions) == 8


@pytest.mark.asyncio
async def test_retry_on_non_dict_payload():
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock("not a dict", _valid_payload()),
    )
    assert len(res.gap_questions) >= MIN_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_retry_on_persona_not_object():
    bad = {"persona": "string instead of object", "gap_questions": []}
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, _valid_payload()),
    )
    assert len(res.gap_questions) >= MIN_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_retry_on_gap_questions_not_list():
    bad = {"persona": {}, "gap_questions": "string instead of list"}
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(bad, _valid_payload()),
    )
    assert len(res.gap_questions) >= MIN_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_retry_on_llm_exception():
    res = await generate_persona(
        **_INPUTS,
        llm_json_fn=_make_llm_mock(RuntimeError("boom"), _valid_payload()),
    )
    assert len(res.gap_questions) >= MIN_GAP_QUESTIONS


# ----------------------------------------------------------------------
# Graceful degradation: never aborts
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_failures_returns_empty_result():
    res = await generate_persona(
        **_INPUTS,
        llm_json_fn=_make_llm_mock(
            "garbage1", "garbage2",
        ),
    )
    # Per PRD: continue with empty output, do not raise
    assert res.gap_questions == []
    assert res.description == ""
    assert res.background_assumptions == []
    assert res.primary_goal == ""


@pytest.mark.asyncio
async def test_two_llm_exceptions_returns_empty_result():
    res = await generate_persona(
        **_INPUTS,
        llm_json_fn=_make_llm_mock(
            RuntimeError("a"), RuntimeError("b"),
        ),
    )
    assert res.gap_questions == []


# ----------------------------------------------------------------------
# Permissive parsing of valid-but-empty fields
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_persona_description_accepted():
    payload = _valid_payload()
    payload["persona"]["description"] = ""
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    # Per PRD: empty description is acceptable, persona is informational
    assert res.description == ""
    assert len(res.gap_questions) >= MIN_GAP_QUESTIONS


@pytest.mark.asyncio
async def test_missing_persona_field_accepted():
    """If 'persona' key is absent entirely, defaults are used."""
    payload = {
        "gap_questions": [
            {"question": f"Q{i}?", "rationale": ""}
            for i in range(MIN_GAP_QUESTIONS)
        ],
    }
    res = await generate_persona(
        **_INPUTS, llm_json_fn=_make_llm_mock(payload),
    )
    assert res.description == ""
    assert res.background_assumptions == []
    assert res.primary_goal == ""
    assert len(res.gap_questions) == MIN_GAP_QUESTIONS


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logs_success(caplog):
    with caplog.at_level("INFO", logger="modules.brief.persona"):
        await generate_persona(
            **_INPUTS, llm_json_fn=_make_llm_mock(_valid_payload()),
        )
    assert any(r.message == "brief.persona.generated" for r in caplog.records)


@pytest.mark.asyncio
async def test_logs_degraded_on_double_failure(caplog):
    with caplog.at_level("WARNING", logger="modules.brief.persona"):
        await generate_persona(
            **_INPUTS,
            llm_json_fn=_make_llm_mock("bad1", "bad2"),
        )
    assert any(r.message == "brief.persona.degraded" for r in caplog.records)
