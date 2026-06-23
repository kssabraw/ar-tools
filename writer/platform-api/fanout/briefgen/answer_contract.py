"""Answer contract (M13 enhancement) — query-understanding guardrail for MCS.

Diagnosed problem (live, `is retatrutide a glp-3 drug`): the answer-engine sources were a
broad retatrutide overview, so the MCS candidate pool was all broad facts and the
coverage-greedy selection wandered into trial/FDA/access subtopics that the brief's own
scope_statement excluded — and never led with the actual answer (GLP-3 is a misnomer; it's
a triple agonist).

The fix is to make the (already-correct) intent understanding a STRUCTURED, ENFORCED
contract instead of a prose scope_statement MCS ignores. One Opus 4.8 call distils:

  - explicit_question / implied_need — what the searcher literally + actually asked,
  - direct_answer + answer_heading — the factual answer (correcting a false premise if the
    query embeds one); answer_heading becomes the GUARANTEED lead H2,
  - must_cover / must_not_cover — the in-scope subtopics + the adjacent topics to exclude;
    the MCS gate drops candidates closer to a must_not_cover topic than to any must_cover.

Opus (not Sonnet) for this one call: it's the reasoning step that sets the whole brief's
direction, it's a single small call (well under the per-brief ceiling), and the answer must
be willing to contradict a false premise in the query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .entity import cosine

logger = logging.getLogger(__name__)

SCOPE_GATE_MARGIN = 0.0   # a candidate is dropped when avoid-cosine > cover-cosine + margin


@dataclass
class AnswerContract:
    explicit_question: str = ""
    implied_need: str = ""
    direct_answer: str = ""
    answer_heading: str = ""                 # the guaranteed lead H2
    must_cover: list[str] = field(default_factory=list)
    must_not_cover: list[str] = field(default_factory=list)

    def as_metadata(self) -> dict:
        return {
            "explicit_question": self.explicit_question, "implied_need": self.implied_need,
            "direct_answer": self.direct_answer, "answer_heading": self.answer_heading,
            "must_cover": self.must_cover, "must_not_cover": self.must_not_cover,
        }


_SCHEMA = {
    "type": "object",
    "properties": {
        "explicit_question": {"type": "string"},
        "implied_need": {"type": "string"},
        "direct_answer": {"type": "string"},
        "answer_heading": {"type": "string"},
        "must_cover": {"type": "array", "items": {"type": "string"}},
        "must_not_cover": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "explicit_question", "implied_need", "direct_answer", "answer_heading",
        "must_cover", "must_not_cover",
    ],
}


def generate_answer_contract(
    keyword: str, *, title: str, scope_statement: str, intent_type: str,
    aio_answer: str, chatgpt_answer: str, llm,
) -> AnswerContract:
    """One Opus tool call. The answer-engine answers are EVIDENCE, not the target — the
    job is to answer the searcher's actual question and set must/must-not-cover guardrails,
    correcting a false premise in the query if one exists. Degrades to an empty contract on
    any failure (MCS then runs unchanged)."""
    try:
        out = llm.call_tool(
            system=(
                "You are a search-intent analyst. Given a search query and the draft article "
                "framing, produce a strict ANSWER CONTRACT a brief generator must obey. Answer "
                "the searcher's ACTUAL question — do not summarize a generic overview. If the "
                "query embeds a false premise (e.g. names a category that does not exist), the "
                "direct_answer must correct it plainly. must_not_cover lists adjacent topics that "
                "would dilute a focused answer (e.g. pricing, where-to-buy, dosing, access) unless "
                "they are core to THIS query."
            ),
            user=(
                f"Search query (keyword): {keyword}\n"
                f"Intent: {intent_type}\n"
                f"Draft title: {title}\n"
                f"Draft scope: {scope_statement}\n\n"
                f"AI Overview answer (evidence):\n{(aio_answer or '(none)')[:2500]}\n\n"
                f"ChatGPT answer (evidence):\n{(chatgpt_answer or '(none)')[:2500]}\n\n"
                "Produce: explicit_question (the literal question), implied_need (what they "
                "actually want to know), direct_answer (1-2 sentences, take a clear position), "
                "answer_heading (a concise H2 <=12 words stating the answer), must_cover (3-6 "
                "short in-scope subtopics that serve the answer), must_not_cover (2-6 short "
                "adjacent topics to exclude)."
            ),
            tool_name="answer_contract",
            tool_description="The structured answer contract.",
            input_schema=_SCHEMA,
            purpose="brief_answer_contract",
            max_tokens=1024,   # NOTE: no temperature — Opus 4.8 rejects it ("deprecated for this model")
        )
    except Exception as exc:  # noqa: BLE001 — enhancement; degrade to unguided MCS
        logger.warning(
            "answer_contract_failed",
            extra={"event": "answer_contract_failed", "keyword": keyword, "reason": repr(exc)},
        )
        return AnswerContract()

    def _strs(v) -> list[str]:
        return [s.strip() for s in v if isinstance(s, str) and s.strip()] if isinstance(v, list) else []

    return AnswerContract(
        explicit_question=(out.get("explicit_question") or "").strip(),
        implied_need=(out.get("implied_need") or "").strip(),
        direct_answer=(out.get("direct_answer") or "").strip(),
        answer_heading=(out.get("answer_heading") or "").strip(),
        must_cover=_strs(out.get("must_cover")),
        must_not_cover=_strs(out.get("must_not_cover")),
    )


def build_scope_gate(
    contract: AnswerContract, embed_fn, *, margin: float = SCOPE_GATE_MARGIN,
):
    """Return a `list[str] -> list[str]` filter that drops candidate headings closer to a
    `must_not_cover` topic than to any `must_cover` topic (one batched embed per call).
    No-op (identity) when the contract has no exclusions."""
    if not contract.must_not_cover:
        return lambda cands: cands
    cover_vecs = embed_fn(contract.must_cover) if contract.must_cover else []
    avoid_vecs = embed_fn(contract.must_not_cover)

    def gate(cands: list[str]) -> list[str]:
        if not cands:
            return cands
        vecs = embed_fn(cands)
        kept: list[str] = []
        for h, hv in zip(cands, vecs):
            cover = max((cosine(hv, cv) for cv in cover_vecs), default=0.0)
            avoid = max((cosine(hv, av) for av in avoid_vecs), default=0.0)
            if avoid <= cover + margin:
                kept.append(h)
        return kept

    return gate
