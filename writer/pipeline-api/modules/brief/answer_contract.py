"""Answer contract — query-understanding guardrail (ported from the fanout brief
generator's `answer_contract.py`, adapted to this module's `claude_json` seam).

One Opus call distils the search query into a STRUCTURED contract the brief obeys:

  - explicit_question / implied_need — what the searcher literally + actually asked,
  - direct_answer + answer_heading — the factual answer (correcting a false premise
    if the query embeds one); answer_heading becomes the GUARANTEED lead H2,
  - must_cover / must_not_cover — in-scope subtopics + adjacent topics to exclude;
    the scope gate drops candidates closer to a must_not_cover topic than to any
    must_cover topic.

The same call also returns a `decision_fit_detection` block (is_multi_answer /
conditions / confidence) so the decision_fit stage (A1) needs no second LLM call.

Opus (not Sonnet): it's the reasoning step that sets the brief's direction and must
be willing to contradict a false premise. Degrades to an empty contract on any
failure, so the pipeline runs exactly as before when it can't be produced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .llm import CLAUDE_OPUS_MODEL, claude_json, cosine, embed_batch_large

logger = logging.getLogger(__name__)

SCOPE_GATE_MARGIN = 0.0  # drop a candidate when avoid-cosine > cover-cosine + margin

LLMJsonFn = Callable[..., Awaitable[Any]]


@dataclass
class AnswerContract:
    explicit_question: str = ""
    implied_need: str = ""
    direct_answer: str = ""
    answer_heading: str = ""  # the guaranteed lead H2
    must_cover: list[str] = field(default_factory=list)
    must_not_cover: list[str] = field(default_factory=list)
    # Decision-fit detection (A1) — folded into this Opus call so decision_fit
    # needs no separate detection LLM round-trip. Not serialized into the brief
    # response; consumed by modules/brief/decision_fit.py.
    decision_fit_detection: dict = field(default_factory=dict)

    def as_metadata(self) -> dict:
        """The 6 contract fields persisted on the brief (detection omitted)."""
        return {
            "explicit_question": self.explicit_question,
            "implied_need": self.implied_need,
            "direct_answer": self.direct_answer,
            "answer_heading": self.answer_heading,
            "must_cover": self.must_cover,
            "must_not_cover": self.must_not_cover,
        }


_SYSTEM = (
    "You are a search-intent analyst. Given a search query and the draft article "
    "framing, produce a strict ANSWER CONTRACT a brief generator must obey. Answer "
    "the searcher's ACTUAL question — do not summarize a generic overview. If the "
    "query embeds a false premise (e.g. names a category that does not exist), the "
    "direct_answer must correct it plainly. must_not_cover lists adjacent topics that "
    "would dilute a focused answer (e.g. pricing, where-to-buy, dosing, access) unless "
    "they are core to THIS query.\n\n"
    "Return ONLY this JSON object:\n"
    "{\n"
    '  "explicit_question": "the literal question",\n'
    '  "implied_need": "what they actually want to know",\n'
    '  "direct_answer": "1-2 sentences, take a clear position",\n'
    '  "answer_heading": "a concise H2 <=12 words stating the answer",\n'
    '  "must_cover": ["3-6 short in-scope subtopics that serve the answer"],\n'
    '  "must_not_cover": ["2-6 short adjacent topics to exclude"],\n'
    '  "decision_fit": {"is_multi_answer": true|false, '
    '"conditions": ["the situational factor that changes the answer"], '
    '"confidence": 0.0}\n'
    "}\n"
    "decision_fit.is_multi_answer is true ONLY when the best answer genuinely depends "
    "on the reader's situation (which option/tier/path fits them); conditions lists the "
    "2+ distinct situational factors; confidence is 0-1."
)


def _strs(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [s.strip() for s in v if isinstance(s, str) and s.strip()]


async def generate_answer_contract(
    keyword: str,
    *,
    title: str,
    scope_statement: str,
    intent_type: str,
    aio_answer: str,
    chatgpt_answer: str,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> AnswerContract:
    """One Opus call. The answer-engine answers are EVIDENCE, not the target — the
    job is to answer the searcher's actual question and set must/must-not-cover
    guardrails, correcting a false premise if one exists. Degrades to an empty
    contract on any failure (the pipeline then runs unchanged)."""
    call = llm_json_fn or claude_json
    user = (
        f"Search query (keyword): {keyword}\n"
        f"Intent: {intent_type}\n"
        f"Draft title: {title}\n"
        f"Draft scope: {scope_statement}\n\n"
        f"AI Overview answer (evidence):\n{(aio_answer or '(none)')[:2500]}\n\n"
        f"ChatGPT answer (evidence):\n{(chatgpt_answer or '(none)')[:2500]}\n\n"
        "Produce the answer-contract JSON now."
    )
    try:
        out = await call(
            _SYSTEM, user, max_tokens=1024, temperature=None, model=CLAUDE_OPUS_MODEL,
        )
    except Exception as exc:  # noqa: BLE001 — enhancement; degrade to no contract
        logger.warning(
            "brief.answer_contract_failed",
            extra={"keyword": keyword, "reason": repr(exc)},
        )
        return AnswerContract()

    if not isinstance(out, dict):
        return AnswerContract()

    detection_raw = out.get("decision_fit")
    detection: dict = {}
    if isinstance(detection_raw, dict):
        detection = {
            "is_multi_answer": bool(detection_raw.get("is_multi_answer")),
            "conditions": _strs(detection_raw.get("conditions")),
            "confidence": _coerce_float(detection_raw.get("confidence")),
        }

    return AnswerContract(
        explicit_question=str(out.get("explicit_question") or "").strip(),
        implied_need=str(out.get("implied_need") or "").strip(),
        direct_answer=str(out.get("direct_answer") or "").strip(),
        answer_heading=str(out.get("answer_heading") or "").strip(),
        must_cover=_strs(out.get("must_cover")),
        must_not_cover=_strs(out.get("must_not_cover")),
        decision_fit_detection=detection,
    )


def _coerce_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_scope_gate(
    contract: AnswerContract,
    embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    *,
    margin: float = SCOPE_GATE_MARGIN,
):
    """Faithful string-filter port: returns an async `list[str] -> list[str]` that
    drops headings closer to a `must_not_cover` topic than to any `must_cover` topic.
    No-op (identity) when the contract lacks BOTH exclusion topics AND cover anchors —
    the comparison is meaningless without cover anchors, and without it every candidate
    with any positive similarity to an avoid topic would be dropped. Used in tests; the
    pipeline uses `partition_candidates_by_scope` to reuse candidate embeddings."""
    if not (contract.must_not_cover and contract.must_cover):
        async def _identity(cands: list[str]) -> list[str]:
            return cands
        return _identity

    n_cover = len(contract.must_cover)

    async def gate(cands: list[str]) -> list[str]:
        if not cands:
            return cands
        topic_vecs = await embed_fn(contract.must_cover + contract.must_not_cover)
        cover_vecs, avoid_vecs = topic_vecs[:n_cover], topic_vecs[n_cover:]
        vecs = await embed_fn(cands)
        kept: list[str] = []
        for h, hv in zip(cands, vecs):
            if not _excludes(hv, cover_vecs, avoid_vecs, margin):
                kept.append(h)
        return kept

    return gate


def _excludes(
    vec: list[float],
    cover_vecs: list[list[float]],
    avoid_vecs: list[list[float]],
    margin: float,
) -> bool:
    cover = max((cosine(vec, cv) for cv in cover_vecs), default=0.0)
    avoid = max((cosine(vec, av) for av in avoid_vecs), default=0.0)
    return avoid > cover + margin


async def partition_candidates_by_scope(
    contract: AnswerContract,
    candidates: list,
    *,
    embed_fn: Optional[Callable[[list[str]], Awaitable[list[list[float]]]]] = None,
    margin: float = SCOPE_GATE_MARGIN,
) -> tuple[list, list]:
    """Split candidate objects into (kept, excluded) using the contract's
    must_not_cover gate, reusing each candidate's pre-computed `.embedding` (no
    re-embed of candidates — only the contract's cover/avoid topics are embedded,
    in a single batched call).

    No-op (returns all kept) unless the contract has BOTH must_not_cover topics AND
    must_cover anchors: without cover anchors the "closer to avoid than to cover"
    test collapses to "any positive similarity to an avoid topic" and would wrongly
    drop nearly the whole pool. A candidate missing an embedding is conservatively
    kept."""
    if not (contract.must_not_cover and contract.must_cover):
        return list(candidates), []
    embed = embed_fn or embed_batch_large
    n_cover = len(contract.must_cover)
    topic_vecs = await embed(contract.must_cover + contract.must_not_cover)
    cover_vecs, avoid_vecs = topic_vecs[:n_cover], topic_vecs[n_cover:]
    kept: list = []
    excluded: list = []
    for c in candidates:
        vec = getattr(c, "embedding", None)
        if not vec:
            kept.append(c)
            continue
        if _excludes(vec, cover_vecs, avoid_vecs, margin):
            excluded.append(c)
        else:
            kept.append(c)
    return kept, excluded
