"""Step 11 - advisory AIO proximity (PRD §X.5).

Computes, for a brief whose SERP carried an AI Overview, how close the
selected headings sit to the AIO answer in embedding space, plus how much
of the AIO fan-out the article covers. This is OBSERVABILITY ONLY: it never
enters compute_priority, MMR, or any gate, and heading_structure is
byte-identical whether or not it runs.

IMPORTANT - not decision-grade. We embed with text-embedding-3-large (to
stay in the same space as the rest of the brief's gates), NOT the model
Google uses to judge AI Overview / AI Mode eligibility. So `proximity_mean`
is a relative, internal signal for the §X.6 measurement loop - do NOT treat
it as a predictor of AIO citation. "Active mode" (proximity as a selection
driver) stays deferred until the live measurement loop validates it.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from .llm import cosine, embed_batch_large

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

# A fan-out question counts as "covered" when some selected heading sits at
# least this close to it. Advisory only - not tuned against live data.
FANOUT_COVERAGE_THRESHOLD = 0.5


async def compute_aio_proximity(
    *,
    heading_texts: list[str],
    fanout_questions: list[str],
    answer_text: str,
    embed_fn: Optional[EmbedFn] = None,
    coverage_threshold: float = FANOUT_COVERAGE_THRESHOLD,
) -> tuple[Optional[float], Optional[float]]:
    """Return (proximity_mean, fanout_coverage_pct), each None when not
    computable (no answer text, or no headings).

    proximity_mean: mean cosine(selected heading, AIO answer).
    fanout_coverage_pct: fraction of AIO fan-out questions for which some
    selected heading is within `coverage_threshold`.
    """
    if not (answer_text or "").strip() or not heading_texts:
        return None, None

    embed = embed_fn or embed_batch_large
    n_head = len(heading_texts)
    texts = [answer_text, *heading_texts, *fanout_questions]
    vecs = await embed(texts)
    if len(vecs) != len(texts):
        return None, None

    answer_vec = vecs[0]
    heading_vecs = vecs[1:1 + n_head]
    fanout_vecs = vecs[1 + n_head:]

    proximities = [cosine(hv, answer_vec) for hv in heading_vecs]
    proximity_mean = round(sum(proximities) / len(proximities), 4) if proximities else None

    coverage: Optional[float] = None
    if fanout_questions:
        covered = 0
        for fv in fanout_vecs:
            best = max((cosine(fv, hv) for hv in heading_vecs), default=0.0)
            if best >= coverage_threshold:
                covered += 1
        coverage = round(covered / len(fanout_questions), 4)

    return proximity_mean, coverage
