"""Step 7 — Heading Priority Scoring (Brief Generator v2.0).

Implements the revised priority formula from PRD §5 Step 7:

    heading_priority = 0.30 × title_relevance
                     + 0.20 × normalized_serp_frequency
                     + 0.10 × position_weight
                     + 0.20 × normalized_llm_consensus
                     + 0.20 × information_gain_score

Plus the information_gain_score tier function:

    1.0 if non-SERP source AND llm_fanout_consensus >= 1
    0.7 if non-SERP source
    0.3 if SERP source only
    0.0 otherwise

Per PRD rationale §5 Step 7:
- title_relevance (0.30) — replaces v1.7's seed similarity. The title is
  the article's actual commitment.
- normalized_serp_frequency (0.20) — proven topical-centrality signal,
  but no longer dominant.
- position_weight (0.10) — reduced from v1.7's 0.15 because top-position
  bias compounds SERP convergence (the failure mode v2.0 fixes).
- normalized_llm_consensus (0.20) — preserved at v1.7 level; cross-model
  agreement is a strong citation-optimization signal.
- information_gain_score (0.20) — NEW. A heading that appears in Reddit/
  PAA/LLM fan-out but not in competitor SERP is exactly the
  differentiation we want to surface.

Operates on v2 Candidate objects from graph.py (mutates `heading_priority`
and `information_gain_score` in place).
"""

from __future__ import annotations

import logging

from .graph import Candidate

logger = logging.getLogger(__name__)


# Sources that count as "SERP" for the information-gain tier. Match the
# definition in graph.py (`_SERP_SOURCES`) so a heading's gain tier and
# its region's information_gain_signal stay consistent.
_SERP_SOURCES: frozenset[str] = frozenset({"serp"})


def information_gain_score(source: str, llm_fanout_consensus: int) -> float:
    """Per-heading information-gain tier (PRD §5 Step 7).

    Higher values indicate the heading represents reader-side demand
    that competitor SERP isn't covering — exactly the differentiation
    the brief should surface.
    """
    is_non_serp = source not in _SERP_SOURCES
    if is_non_serp and llm_fanout_consensus >= 1:
        return 1.0
    if is_non_serp:
        return 0.7
    # SERP only
    return 0.3


def compute_priority(candidates: list[Candidate]) -> None:
    """Stamp `information_gain_score` and `heading_priority` on each
    candidate, in place. Idempotent — safe to call repeatedly.

    Assumes `title_relevance` is already populated (graph.embed_with_gates
    handles that). For candidates with `avg_serp_position == None` the
    position component contributes 0.5 (a neutral midpoint) so non-SERP
    headings aren't unfairly penalized — matches the PRD formula.
    """
    for c in candidates:
        gain = information_gain_score(c.source, c.llm_fanout_consensus or 0)
        c.information_gain_score = gain

        norm_freq = min((c.serp_frequency or 0) / 20.0, 1.0)

        if c.avg_serp_position is not None:
            position_weight = max(1.0 - ((c.avg_serp_position - 1) / 20.0), 0.0)
        else:
            position_weight = 0.5  # PRD §5 Step 7 neutral default

        norm_consensus = min((c.llm_fanout_consensus or 0) / 4.0, 1.0)

        c.heading_priority = (
            0.30 * c.title_relevance
            + 0.20 * norm_freq
            + 0.10 * position_weight
            + 0.20 * norm_consensus
            + 0.20 * gain
        )

    logger.info(
        "brief.priority.computed",
        extra={
            "candidate_count": len(candidates),
            "max_priority": (
                round(max((c.heading_priority for c in candidates), default=0.0), 4)
            ),
            "min_priority": (
                round(min((c.heading_priority for c in candidates), default=0.0), 4)
            ),
        },
    )
