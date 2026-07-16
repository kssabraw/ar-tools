"""Step 11 - advisory AIO proximity (PRD §X.5).

Computes, for a brief whose SERP carried an AI Overview, how close the
selected headings sit to the AIO answer in embedding space, plus how much
of the AIO fan-out the article covers. This is OBSERVABILITY ONLY: it never
enters compute_priority, MMR, or any gate, and heading_structure is
byte-identical whether or not it runs.

Embedding space (v2.8): when a GEMINI_API_KEY is configured, headings embed as
RETRIEVAL_QUERY and the AIO answer + fan-out questions embed as
RETRIEVAL_DOCUMENT — Gemini's asymmetric retrieval spaces track Google's AI
Overview retrieval better than a symmetric space. On a Gemini error it falls
back to `embed_batch_large` (the symmetric SEMANTIC_SIMILARITY space — also
Gemini now that the suite has standardized off OpenAI).

IMPORTANT - still not decision-grade. `proximity_mean` is a relative, internal
signal for the §X.6 measurement loop — do NOT treat it as a predictor of AIO
citation. "Active mode" (proximity as a selection driver) stays deferred until
the live measurement loop validates it.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from .llm import (
    cosine,
    embed_batch_large,
    embed_gemini_document,
    embed_gemini_query,
    gemini_configured,
)

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

# A fan-out question counts as "covered" when some selected heading sits at
# least this close to it. Advisory only - not tuned against live data.
FANOUT_COVERAGE_THRESHOLD = 0.5


def _scores(
    heading_vecs: list[list[float]],
    answer_vec: list[float],
    fanout_vecs: list[list[float]],
    fanout_count: int,
    coverage_threshold: float,
) -> tuple[Optional[float], Optional[float]]:
    """Pure scoring shared by the dual-space and fallback paths."""
    proximities = [cosine(hv, answer_vec) for hv in heading_vecs]
    proximity_mean = (
        round(sum(proximities) / len(proximities), 4) if proximities else None
    )

    coverage: Optional[float] = None
    if fanout_count:
        covered = 0
        for fv in fanout_vecs:
            best = max((cosine(fv, hv) for hv in heading_vecs), default=0.0)
            if best >= coverage_threshold:
                covered += 1
        coverage = round(covered / fanout_count, 4)

    return proximity_mean, coverage


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

    Uses Gemini dual-space (asymmetric) embeddings when configured (and
    `embed_fn` is not explicitly overridden); otherwise — or on any Gemini error
    — falls back to the single-space `embed_batch_large` (Gemini
    SEMANTIC_SIMILARITY).
    """
    if not (answer_text or "").strip() or not heading_texts:
        return None, None

    # Dual-space path: only when Gemini is configured AND the caller didn't pin a
    # specific embed_fn (tests / callers can force the single-space path).
    if embed_fn is None and gemini_configured():
        try:
            heading_vecs = await embed_gemini_query(heading_texts)
            doc_vecs = await embed_gemini_document([answer_text, *fanout_questions])
            if (
                len(heading_vecs) == len(heading_texts)
                and len(doc_vecs) == 1 + len(fanout_questions)
            ):
                answer_vec = doc_vecs[0]
                fanout_vecs = doc_vecs[1:]
                return _scores(
                    heading_vecs, answer_vec, fanout_vecs,
                    len(fanout_questions), coverage_threshold,
                )
            logger.warning("brief.aio_proximity.gemini_count_mismatch")
        except Exception as exc:  # noqa: BLE001 — advisory; fall back to embed_batch_large
            logger.warning(
                "brief.aio_proximity.gemini_failed",
                extra={"reason": repr(exc)},
            )

    # Single-space fallback (Gemini SEMANTIC_SIMILARITY) — one batched call.
    embed = embed_fn or embed_batch_large
    n_head = len(heading_texts)
    texts = [answer_text, *heading_texts, *fanout_questions]
    vecs = await embed(texts)
    if len(vecs) != len(texts):
        return None, None

    answer_vec = vecs[0]
    heading_vecs = vecs[1:1 + n_head]
    fanout_vecs = vecs[1 + n_head:]
    return _scores(
        heading_vecs, answer_vec, fanout_vecs,
        len(fanout_questions), coverage_threshold,
    )
