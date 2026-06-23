"""Brief Generator Steps 7-8 — Max Cosine Synthesis (M13 slice 4, §4.X / §0).

MCS replaces the organic H2-selection layer (aio §0 #3). It builds the H2 skeleton to
sit close to the live answer-engine answers, then optimizes the SET for coverage:

- **Form** (X.4): every heading = main entity + exactly one point the answer makes
  (baked into the LLM candidate generation).
- **Dual-space, scalar-blended** (the "never mix vectors" lock, §0 cross-space rule):
  score each candidate against the **AIO answer in Gemini space** and the **ChatGPT
  answer in 3-large space**, then blend the two **scalars** 0.5/0.5 (never average the
  vectors). Eligibility = clears the floor on at least one engine.
- **Synthesis = set coverage** (greedy/beam monotonic climb): decompose the AIO answer
  into points; pick the heading that most increases the set's coverage of those points
  (+ the ChatGPT target), climb until the marginal gain < ε or the H2 cap, never pad
  past available candidates (honest shortfall).

Pure core (split / blend / score / select) is fixture-tested; candidate generation
(Haiku) and the dual embedders are injected (`MCSDeps`) and validated live.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from .entity import cosine

logger = logging.getLogger(__name__)

# Defaults (module constants like entity/gates; the pipeline slice may override).
POOL_SIZE = 24                 # candidates generated per Haiku call
BEAM_ROUNDS = 2                # variation rounds around the winners (owner: ~2)
MIN_H2 = 3                     # floor; overridden by the intent template's anchor slots
MAX_H2 = 12                    # cap (aio §0 #4: 8-12)
EPSILON = 0.01                 # marginal-coverage-gain stop threshold
W_AIO = 0.5
W_CHATGPT = 0.5
MAX_POINTS = 20                # answer is decomposed into at most this many points
ENGINE_FLOOR = 0.0             # per-engine eligibility floor (recalibrate after X.6)

EmbedFn = Callable[[list[str]], list[list[float]]]


# ----- pure: answer decomposition + scoring + selection ---------------------


def split_into_points(answer: str, *, max_points: int = MAX_POINTS) -> list[str]:
    """Decompose an answer into distinct points (sentences) — the coverage sub-targets.
    Falls back to the whole answer if it has no sentence punctuation."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer or "") if s.strip()]
    if not sents:
        return [answer.strip()] if (answer or "").strip() else []
    return sents[:max_points]


def blended_score(
    aio_headline: float, chatgpt_cosine: float, *, aio_present: bool,
    chatgpt_present: bool, w_aio: float = W_AIO, w_chatgpt: float = W_CHATGPT,
) -> float:
    """0.5/0.5 blend of the two engine scalars, engine-aware: if only one engine is
    present, the score IS that engine's (no half-credit penalty for a missing engine)."""
    if aio_present and chatgpt_present:
        return w_aio * aio_headline + w_chatgpt * chatgpt_cosine
    if aio_present:
        return aio_headline
    if chatgpt_present:
        return chatgpt_cosine
    return 0.0


@dataclass
class ScoredHeading:
    text: str
    point_cosines: list[float]      # cosine to each AIO answer point (Gemini space)
    chatgpt_cosine: float           # cosine to the ChatGPT answer (3-large space)
    aio_headline: float             # max point cosine (the heading's AIO closeness)
    blended: float


def score_headings(
    candidates: list[str], *, cand_aio_vecs: list[list[float]],
    cand_3l_vecs: list[list[float]], point_aio_vecs: list[list[float]],
    chatgpt_vec: list[float] | None, aio_present: bool, chatgpt_present: bool,
    w_aio: float = W_AIO, w_chatgpt: float = W_CHATGPT,
) -> list[ScoredHeading]:
    """Pure dual-space scoring given pre-computed vectors. AIO closeness = max cosine to
    any answer point (Gemini); ChatGPT closeness = cosine to the ChatGPT answer
    (3-large). Blended per `blended_score`."""
    out: list[ScoredHeading] = []
    for text, av, cv in zip(candidates, cand_aio_vecs, cand_3l_vecs):
        point_cos = [cosine(av, pv) for pv in point_aio_vecs] if aio_present else []
        cg = cosine(cv, chatgpt_vec) if (chatgpt_present and chatgpt_vec is not None) else 0.0
        aio_headline = max(point_cos) if point_cos else 0.0
        out.append(ScoredHeading(
            text=text, point_cosines=point_cos, chatgpt_cosine=cg,
            aio_headline=aio_headline,
            blended=blended_score(aio_headline, cg, aio_present=aio_present,
                                  chatgpt_present=chatgpt_present, w_aio=w_aio, w_chatgpt=w_chatgpt),
        ))
    return out


def select_by_coverage(
    scored: list[ScoredHeading], *, min_count: int = MIN_H2, max_count: int = MAX_H2,
    epsilon: float = EPSILON, w_aio: float = W_AIO, w_chatgpt: float = W_CHATGPT,
    engine_floor: float = ENGINE_FLOOR, aio_present: bool = True, chatgpt_present: bool = True,
) -> list[ScoredHeading]:
    """Greedy set-coverage climb. coverage(set) blends, per the two engines:
      AIO  : mean over answer points of (best selected cosine to that point)
      GPT  : best selected cosine to the ChatGPT answer
    Each round adds the eligible candidate with the largest MARGINAL coverage gain.
    Stops once >= `min_count` are chosen and the next gain < `epsilon`, or at
    `max_count`, or when no eligible candidate remains (honest shortfall — never pad)."""
    eligible = [
        s for s in scored
        if (aio_present and s.aio_headline >= engine_floor)
        or (chatgpt_present and s.chatgpt_cosine >= engine_floor)
    ]
    if not eligible:
        return []
    n_points = max((len(s.point_cosines) for s in eligible), default=0)

    selected: list[ScoredHeading] = []
    remaining = list(eligible)
    best_point = [0.0] * n_points
    best_chatgpt = 0.0

    def marginal(c: ScoredHeading) -> float:
        aio_gain = 0.0
        if aio_present and n_points and c.point_cosines:
            aio_gain = sum(
                max(0.0, c.point_cosines[p] - best_point[p]) for p in range(len(c.point_cosines))
            ) / n_points
        gpt_gain = max(0.0, c.chatgpt_cosine - best_chatgpt) if chatgpt_present else 0.0
        return blended_score(aio_gain, gpt_gain, aio_present=aio_present,
                             chatgpt_present=chatgpt_present, w_aio=w_aio, w_chatgpt=w_chatgpt)

    while remaining and len(selected) < max_count:
        best = max(remaining, key=marginal)
        gain = marginal(best)
        if len(selected) >= min_count and gain < epsilon:
            break
        selected.append(best)
        remaining.remove(best)
        for p in range(len(best.point_cosines)):
            best_point[p] = max(best_point[p], best.point_cosines[p])
        best_chatgpt = max(best_chatgpt, best.chatgpt_cosine)
    return selected


# ----- egress: candidate generation (Haiku) + orchestration -----------------


@dataclass
class MCSDeps:
    gen_llm: object                 # AnthropicLLM (Haiku) — candidate generation
    embed_aio_query: EmbedFn        # Gemini RETRIEVAL_QUERY (headings)
    embed_aio_doc: EmbedFn          # Gemini RETRIEVAL_DOCUMENT (answer points)
    embed_3large: EmbedFn           # OpenAI text-embedding-3-large (ChatGPT + headings)


@dataclass
class MCSResult:
    selected: list[ScoredHeading] = field(default_factory=list)
    pool: list[str] = field(default_factory=list)        # every candidate generated
    discarded: list[ScoredHeading] = field(default_factory=list)


def generate_candidate_pool(
    *, entity: str, points: list[str], keyword: str, llm, pool_size: int = POOL_SIZE,
    seed_winners: list[str] | None = None, intent_hint: str | None = None,
) -> list[str]:
    """Haiku (tool-use): generate heading candidates in the X.4 form — `<main entity> +
    one specific point the answer makes`, exactly one point each, no bare topic words.
    `seed_winners` (beam rounds) asks for variations around the current best headings."""
    schema = {
        "type": "object",
        "properties": {"headings": {"type": "array", "items": {"type": "string"}}},
        "required": ["headings"],
    }
    pts = "\n".join(f"- {p}" for p in points[:20]) or "(no answer points available)"
    variation = (
        "\n\nGenerate variations around these strong headings (keep what works, vary the point):\n"
        + "\n".join(f"- {w}" for w in seed_winners)
        if seed_winners else ""
    )
    out = llm.call_tool(
        system=(
            "You generate H2 heading candidates for an article, optimized to match an "
            "AI answer. RULES: every heading = the main entity, then ONE specific point "
            "the answer actually makes, in that order. Exactly one point per heading. "
            "Never use a bare topic word ('meaning', 'benefits', 'overview'). Vary the "
            "point across headings so the set covers the answer's distinct points."
        ),
        user=(
            f"Main entity: {entity}\nTarget keyword: {keyword}\n\n"
            f"Points the answer makes:\n{pts}{variation}\n\n"
            f"Return {pool_size} distinct heading candidates."
        ),
        tool_name="generate_headings",
        tool_description="Return entity+one-point heading candidates.",
        input_schema=schema,
        purpose="mcs_candidate_gen",
    )
    seen: set[str] = set()
    pool: list[str] = []
    for h in out.get("headings", []):
        if isinstance(h, str) and h.strip() and h.strip().lower() not in seen:
            seen.add(h.strip().lower())
            pool.append(h.strip())
    return pool[:pool_size]


def run_mcs(
    *, entity: str, aio: dict, chatgpt_answer: str | None, keyword: str, deps: MCSDeps,
    pool_size: int = POOL_SIZE, beam_rounds: int = BEAM_ROUNDS, min_count: int = MIN_H2,
    max_count: int = MAX_H2, epsilon: float = EPSILON, w_aio: float = W_AIO,
    w_chatgpt: float = W_CHATGPT, gate_fn: Callable[[list[str]], list[str]] | None = None,
) -> MCSResult:
    """Orchestrate MCS: generate a candidate pool (+ beam variation rounds), score in
    both spaces, and select by coverage. `aio` is the X.1 dict
    {present, answer_text, cited_sources}; `chatgpt_answer` is the Step-2D ChatGPT text.
    Embeds the answer targets once and reuses them across rounds."""
    aio_present = bool(aio.get("present") and (aio.get("answer_text") or "").strip())
    chatgpt_present = bool((chatgpt_answer or "").strip())
    if not aio_present and not chatgpt_present:
        # No answer-engine target — MCS cannot score; the pipeline degrades to the
        # gate-passed candidates / organic selection (handled upstream).
        logger.warning("mcs_no_targets", extra={"event": "mcs_no_targets", "keyword": keyword})
        return MCSResult()

    points = split_into_points(aio.get("answer_text", "")) if aio_present else []
    point_aio_vecs = deps.embed_aio_doc(points) if points else []
    chatgpt_vec = deps.embed_3large([chatgpt_answer])[0] if chatgpt_present else None

    pool: list[str] = []
    scored: list[ScoredHeading] = []
    seed_winners: list[str] = []
    for round_i in range(max(1, beam_rounds)):
        fresh = generate_candidate_pool(
            entity=entity, points=points, keyword=keyword, llm=deps.gen_llm,
            pool_size=pool_size, seed_winners=seed_winners or None,
        )
        fresh = [h for h in fresh if h.lower() not in {p.lower() for p in pool}]
        if gate_fn is not None and fresh:
            # Eligibility pre-filter (X.3): drop off-topic / pure-restatement candidates
            # before they reach scoring + coverage selection.
            kept = set(gate_fn(fresh))
            fresh = [h for h in fresh if h in kept]
        if not fresh:
            if round_i == 0:
                continue   # first pool fully gated out — try a variation round before giving up
            break
        pool.extend(fresh)
        cand_aio_vecs = deps.embed_aio_query(fresh) if aio_present else [[] for _ in fresh]
        cand_3l_vecs = deps.embed_3large(fresh)
        scored.extend(score_headings(
            fresh, cand_aio_vecs=cand_aio_vecs, cand_3l_vecs=cand_3l_vecs,
            point_aio_vecs=point_aio_vecs, chatgpt_vec=chatgpt_vec,
            aio_present=aio_present, chatgpt_present=chatgpt_present,
            w_aio=w_aio, w_chatgpt=w_chatgpt,
        ))
        selected = select_by_coverage(
            scored, min_count=min_count, max_count=max_count, epsilon=epsilon,
            w_aio=w_aio, w_chatgpt=w_chatgpt, aio_present=aio_present,
            chatgpt_present=chatgpt_present,
        )
        seed_winners = [s.text for s in selected[:5]]

    selected = select_by_coverage(
        scored, min_count=min_count, max_count=max_count, epsilon=epsilon,
        w_aio=w_aio, w_chatgpt=w_chatgpt, aio_present=aio_present, chatgpt_present=chatgpt_present,
    )
    sel_texts = {s.text for s in selected}
    return MCSResult(
        selected=selected, pool=pool,
        discarded=[s for s in scored if s.text not in sel_texts],
    )
