"""Tests for the brief answer-contract stage (schema v2.8)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pytest

from modules.brief.answer_contract import (
    AnswerContract,
    build_scope_gate,
    generate_answer_contract,
    partition_candidates_by_scope,
)

# Deterministic 3-axis unit vectors keyed by topic word, so cosine cleanly
# separates "cover"-aligned text (axis 0) from "avoid"-aligned text (axis 1).
_VECS = {
    "cover": [1.0, 0.0, 0.0],
    "avoid": [0.0, 1.0, 0.0],
    "other": [0.0, 0.0, 1.0],
}


def _bucket(text: str) -> str:
    t = text.lower()
    if "avoid" in t:
        return "avoid"
    if "cover" in t:
        return "cover"
    return "other"


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    return [_VECS[_bucket(t)] for t in texts]


@dataclass
class _Cand:
    text: str
    embedding: Optional[list[float]]


async def test_generate_answer_contract_parses_all_fields():
    async def fake_llm(system, user, **kwargs):
        # Opus call: temperature omitted, model overridden.
        assert kwargs.get("temperature") is None
        assert kwargs.get("model")
        return {
            "explicit_question": "Is X a Y?",
            "implied_need": "whether X belongs to category Y",
            "direct_answer": "No — X is actually a Z.",
            "answer_heading": "Why X Is a Z, Not a Y",
            "must_cover": ["the Z mechanism", "  ", "how X works"],
            "must_not_cover": ["pricing", "where to buy"],
            "decision_fit": {
                "is_multi_answer": True,
                "conditions": ["if you need A", "if you need B"],
                "confidence": 0.82,
            },
        }

    c = await generate_answer_contract(
        "x keyword", title="T", scope_statement="S", intent_type="informational",
        aio_answer="aio", chatgpt_answer="cg", llm_json_fn=fake_llm,
    )
    assert c.explicit_question == "Is X a Y?"
    assert c.answer_heading == "Why X Is a Z, Not a Y"
    assert c.must_cover == ["the Z mechanism", "how X works"]  # blanks dropped
    assert c.must_not_cover == ["pricing", "where to buy"]
    assert c.decision_fit_detection["is_multi_answer"] is True
    assert c.decision_fit_detection["confidence"] == 0.82
    assert c.as_metadata().keys() >= {"explicit_question", "must_not_cover"}
    assert "decision_fit_detection" not in c.as_metadata()  # detection not serialized


async def test_generate_answer_contract_degrades_on_failure():
    async def boom(system, user, **kwargs):
        raise RuntimeError("opus down")

    c = await generate_answer_contract(
        "x", title="T", scope_statement="S", intent_type="informational",
        aio_answer="", chatgpt_answer="", llm_json_fn=boom,
    )
    assert c == AnswerContract()
    assert c.must_not_cover == []


async def test_partition_candidates_by_scope_drops_avoid_aligned():
    contract = AnswerContract(must_cover=["cover topic"], must_not_cover=["avoid topic"])
    cands = [
        _Cand("cover-aligned heading", _VECS["cover"]),
        _Cand("avoid-aligned heading", _VECS["avoid"]),
        _Cand("neutral heading", _VECS["other"]),
        _Cand("no embedding heading", None),  # conservatively kept
    ]
    kept, excluded = await partition_candidates_by_scope(
        contract, cands, embed_fn=_fake_embed,
    )
    kept_text = {c.text for c in kept}
    assert "avoid-aligned heading" in {c.text for c in excluded}
    assert "cover-aligned heading" in kept_text
    assert "no embedding heading" in kept_text  # missing embedding never dropped


async def test_partition_no_exclusions_is_noop():
    contract = AnswerContract(must_cover=["cover"], must_not_cover=[])
    cands = [_Cand("avoid-aligned", _VECS["avoid"])]
    kept, excluded = await partition_candidates_by_scope(contract, cands, embed_fn=_fake_embed)
    assert excluded == []
    assert len(kept) == 1


async def test_build_scope_gate_string_filter():
    contract = AnswerContract(must_cover=["cover"], must_not_cover=["avoid"])
    gate = build_scope_gate(contract, _fake_embed)
    kept = await gate(["a cover heading", "an avoid heading", "other heading"])
    assert "a cover heading" in kept
    assert "an avoid heading" not in kept

    # No exclusions → identity.
    identity = build_scope_gate(AnswerContract(must_not_cover=[]), _fake_embed)
    assert await identity(["an avoid heading"]) == ["an avoid heading"]
