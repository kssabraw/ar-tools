"""Shared structural-fidelity gate for single-call HTML generators.

Both the Local SEO page generator and the Ecommerce product generator produce a
whole page in one nlp call against a "mirror this layout" reference, then persist
the result. Neither engine measured whether the output actually matched the
reference structure, so the writer drifted (wrong section count/order, dropped
FAQ/table/CTA blocks). This module closes that loop identically for both:

    score the generated HTML outline against the stored reference analysis
    → if it drifts on layout below a threshold, regenerate with the specific
      misses fed back → keep the best-scoring pass, capped.

The per-engine caller supplies a `regenerate(corrections)` coroutine (its own nlp
call with the corrections threaded in) so this stays engine-agnostic. The
service/location Writer uses a different mechanism (its reoptimize pass is driven
by the scorer's deficiency list) and does NOT use this helper — see
page_structure_eval.structure_deficiency.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def apply_structure_gate(
    result: dict,
    reference_analysis: Optional[dict],
    regenerate: Callable[[str], Awaitable[Optional[dict]]],
    *,
    enabled: bool,
    min_composite: float,
    max_passes: int,
    content_key: str = "content_html",
    log_tag: str = "structure_gate",
) -> dict:
    """Keep-best structural gate for a single-call generator.

    `result` is the generator's result dict (carrying HTML under `content_key`).
    `reference_analysis` is the stored reference structure analysis to score
    against (None → gate is a no-op). `regenerate(corrections)` re-runs generation
    with the corrections fed back and returns a new result dict (or None on
    failure). Returns the best-scoring result with its structural verdict attached
    under `structure_fidelity`. Deterministic scoring, best-effort: any
    scoring/regeneration failure returns the best result so far and never raises.
    """
    if not enabled or not reference_analysis:
        return result

    from services.page_structure_eval import (
        build_structure_corrections,
        extract_outline_from_html,
        score_structural_fidelity,
    )

    def _fidelity(res: dict) -> Optional[dict[str, Any]]:
        try:
            generated = extract_outline_from_html(res.get(content_key) or "")
            return score_structural_fidelity(reference_analysis, generated)
        except Exception:  # noqa: BLE001 — scoring must never break the run
            logger.warning("%s.score_failed", log_tag)
            return None

    best = result
    best_fid = _fidelity(result)
    if best_fid is None:
        return result
    best_score = best_fid.get("composite") or 0.0

    for pass_num in range(1, max_passes + 1):
        if best_score >= min_composite:
            break
        gen_outline = extract_outline_from_html(best.get(content_key) or "")
        corrections = build_structure_corrections(reference_analysis, gen_outline)
        if not corrections:
            break  # nothing concrete to correct — don't spend a pass
        try:
            candidate = await regenerate(corrections)
        except Exception:  # noqa: BLE001 — regen failure keeps the best so far
            logger.warning("%s.regen_failed", log_tag, extra={"pass": pass_num})
            break
        if not candidate:
            break
        cand_fid = _fidelity(candidate)
        cand_score = (cand_fid or {}).get("composite") or 0.0
        logger.info(
            "%s.pass" % log_tag,
            extra={"pass": pass_num, "prev_score": best_score, "cand_score": cand_score},
        )
        if cand_fid is not None and cand_score > best_score:
            best, best_fid, best_score = candidate, cand_fid, cand_score

    logger.info(
        "%s.final" % log_tag,
        extra={"composite": best_score, "passed": best_score >= min_composite},
    )
    best = dict(best)
    best["structure_fidelity"] = best_fid
    return best
