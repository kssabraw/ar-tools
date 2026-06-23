"""LLM routing for ambiguous keywords (routing-calibration second pass).

After the gate's cosine Lever-3 picks a best silo for each keyword, identify
the ambiguous cases — those whose top-1 vs top-2 silo-anchor cosine margin is
below a threshold — and have the LLM rule on them in batches. Cheap because
only the ambiguous fraction goes through the LLM; the easy cases stay on the
fast embedding path.

Each ambiguous keyword carries the gate's full candidate-silo list (the silos
in which the keyword was a candidate); the LLM may pick any of them. If the
LLM picks a silo NOT in the candidate list (it shouldn't, but defensive), the
caller ignores that pick — the cosine assignment stands.

Failure is benign: a batch that errors yields no reassignments for its
keywords, which keep their cosine routing.
"""

from __future__ import annotations

import logging
from typing import Callable

from fanout.concurrency import ContextThreadPoolExecutor

logger = logging.getLogger(__name__)


# Each ambiguous entry: (keyword, candidate_silo_ids).
# The router returns: {keyword: new_silo_id} only for reassignments.
LLMRouter = Callable[[list[tuple[str, list[str]]]], dict[str, str]]


def build_llm_router(
    *,
    seed: str,
    silos: list[dict],
    llm,
    batch_size: int = 50,
    max_workers: int = 4,
) -> LLMRouter:
    """Build a callable that re-routes ambiguous keywords via the LLM. The
    closure holds the seed + silo metadata so the caller (the gate) only needs
    to pass the ambiguous batch — keeping the gate decoupled from the LLM."""
    silos_by_id = {s["id"]: s for s in silos}

    def _route_batch(batch: list[tuple[str, list[str]]]) -> dict[str, str]:
        keywords = [kw for kw, _ in batch]
        try:
            picks = llm.route_ambiguous_keywords(
                seed=seed, silos=silos, keywords=keywords,
            )
        except Exception as exc:  # noqa: BLE001 — degrade this batch, keep cosine
            logger.warning(
                "llm_routing_batch_failed",
                extra={"event": "llm_routing_batch_failed", "reason": repr(exc),
                       "batch_size": len(batch)},
            )
            return {}
        out: dict[str, str] = {}
        for kw, cands in batch:
            picked = picks.get(kw)
            if picked and picked in cands:
                out[kw] = picked
        return out

    def router(ambiguous: list[tuple[str, list[str]]]) -> dict[str, str]:
        if not ambiguous or not silos_by_id:
            return {}
        # Slice into batches and run them in parallel.
        batches: list[list[tuple[str, list[str]]]] = [
            ambiguous[i : i + batch_size]
            for i in range(0, len(ambiguous), batch_size)
        ]
        out: dict[str, str] = {}
        with ContextThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            for batch_out in ex.map(_route_batch, batches):
                out.update(batch_out)
        logger.info(
            "llm_routing_complete",
            extra={"event": "llm_routing_complete",
                   "ambiguous_total": len(ambiguous),
                   "batches": len(batches),
                   "reassigned": len(out)},
        )
        return out

    return router
