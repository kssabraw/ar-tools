"""Step 7.6 - LLM Heading Quality Scoring (PRD v2.4).

Adds a qualitative LLM signal on top of the existing vector-based
`heading_priority` (priority.py). Vector signals stay primary (SEO/AEO
ranking still dominates); the LLM bell-curve score adds discrimination
on dimensions vector embeddings can't see - engagement value and
information depth.

Ported pattern: the n8n "Score Headings" stage from the Content Brief
workflow. Three axes per heading, each scored 0–3:
  - topical_relevance (0=off-topic, 3=core intent)
  - engagement_value (0=dull/generic, 3=highly clickable/useful)
  - information_depth (0=redundant/shallow, 3=expert synthesis)

Bell-curve constraint enforced in the prompt: full 0–3 range across the
candidate set, ~15% top scores only, mean near 2.0.

Cost-bounded:
  - Only the top-K candidates by `heading_priority` are sent to the LLM
    (default K=25 via `brief_llm_scoring_top_k`). MMR / anchor reservation
    rarely look beyond this window, so scoring deeper is wasted tokens.
  - One batched LLM call per brief (~$0.01).

Combination rule:
  combined = (1 - w) * heading_priority + w * llm_quality_score
  where w = `brief_llm_scoring_weight` (default 0.30 - vector still
  dominates at 70%). Mutates `heading_priority` in place so downstream
  consumers (Step 7.5 anchor reservation, Step 8 MMR, Step 8.6 H3
  selection) consume the combined score transparently.

Failure handling: never aborts. LLM call exception, malformed response,
or empty scores → leaves `heading_priority` untouched and logs
`brief.llm_scoring.{llm_failed,no_valid_scores}`. Brief continues with
pure vector priority.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from config import settings

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


# Score range each axis is expected to produce. Values outside this
# range are clamped during normalization.
SCORE_MIN = 0
SCORE_MAX = 3
# Sum across the three axes maxes at SCORE_MAX * 3 = 9.
_SCORE_AXIS_COUNT = 3
_SCORE_DENOMINATOR = float(SCORE_MAX * _SCORE_AXIS_COUNT)


LLMJsonFn = Callable[..., Awaitable[Any]]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMScoringResult:
    """Outcome of `score_top_candidates_llm`.

    `scored_count` is the number of candidates whose `llm_quality_score`
    was populated. `priority_changed_count` is the subset whose
    `heading_priority` was mutated by the blend. `llm_failed` indicates
    the call raised; `no_valid_scores` indicates a response that parsed
    but contained zero usable score entries.
    """

    scored_count: int = 0
    priority_changed_count: int = 0
    llm_called: bool = False
    llm_failed: bool = False
    no_valid_scores: bool = False
    skipped_reason: Optional[str] = None
    score_distribution: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SCORING_SYSTEM_PROMPT = """\
You are a senior content strategist scoring blog post H2 candidates.

For each heading, assign three integer scores from 0 to 3:

  topical_relevance:
    0 = off-topic for the article's keyword
    1 = tangentially related; would feel like a digression
    2 = clearly on-topic
    3 = core to the reader's intent - the article fails without it

  engagement_value:
    0 = dull, generic, boilerplate ("Overview", "Introduction")
    1 = ok but unmemorable
    2 = good hook - surfaces a real reason to keep reading
    3 = highly clickable / useful - the heading itself promises specific value

  information_depth:
    0 = redundant or shallow (paraphrases another heading; common knowledge)
    1 = covers familiar ground without new angle
    2 = substantive - readers learn something concrete
    3 = expert synthesis - covers a non-obvious angle, hidden trade-off,
        or insider insight competitor articles miss

BELL-CURVE CONSTRAINT (mandatory):
- Use the FULL 0-3 range across the candidate set.
- Only the top ~15% of headings should receive 3 on any axis.
- The mean across all axes should be approximately 2.0.
- DO NOT cluster all candidates at 2 or 3 - that defeats scoring purpose.
- It is OK and expected for some candidates to receive 0 or 1.

OUTPUT (strict JSON only, no preamble, no markdown fences):
{
  "scores": [
    {"index": 0, "topical_relevance": 2, "engagement_value": 3, "information_depth": 2},
    ...
  ]
}

Return one entry per input heading, in the same order, with the same
indices. Integers only - no floats, no strings."""


def _build_user_prompt(
    *,
    keyword: str,
    title: str,
    intent: str,
    candidates: list[Candidate],
) -> str:
    items = [
        {"index": i, "text": c.text}
        for i, c in enumerate(candidates)
    ]
    return (
        f"Article keyword: {keyword}\n"
        f"Article title: {title}\n"
        f"Article intent: {intent}\n\n"
        f"Score the following H2 candidates against the rubric, applying "
        f"the bell-curve constraint across this set:\n"
        f"{json.dumps(items, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# Score parsing + clamping
# ---------------------------------------------------------------------------


def _clamp_score(raw: Any) -> Optional[int]:
    """Return raw as int in [SCORE_MIN, SCORE_MAX], or None when invalid."""
    if isinstance(raw, bool):  # bool is an int in Python - exclude explicitly
        return None
    if isinstance(raw, int):
        return max(SCORE_MIN, min(SCORE_MAX, raw))
    if isinstance(raw, float) and raw.is_integer():
        return max(SCORE_MIN, min(SCORE_MAX, int(raw)))
    return None


def _normalize_quality(
    topical: int, engagement: int, depth: int,
) -> float:
    """Combine three axis scores into a single 0-1 quality score."""
    total = topical + engagement + depth
    return total / _SCORE_DENOMINATOR


# ---------------------------------------------------------------------------
# Distribution tracking (for log visibility into bell-curve compliance)
# ---------------------------------------------------------------------------


def _distribution_summary(
    candidates: list[Candidate],
) -> dict[str, float]:
    """Cheap stats for the structured log line - operators can tell at a
    glance whether the LLM is collapsing all scores into a narrow band."""
    if not candidates:
        return {}
    quality = [c.llm_quality_score for c in candidates]
    return {
        "mean_quality": round(sum(quality) / len(quality), 4),
        "min_quality": round(min(quality), 4),
        "max_quality": round(max(quality), 4),
        "top_score_share": round(
            sum(
                1 for c in candidates
                if c.llm_topical_relevance == SCORE_MAX
                or c.llm_engagement_value == SCORE_MAX
                or c.llm_information_depth == SCORE_MAX
            ) / len(candidates),
            4,
        ),
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def score_top_candidates_llm(
    candidates: list[Candidate],
    *,
    keyword: str,
    title: str,
    intent: str,
    weight: Optional[float] = None,
    top_k: Optional[int] = None,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> LLMScoringResult:
    """LLM-score the top-K candidates by vector priority and blend the
    quality score into `heading_priority` in place.

    No-ops (returns `skipped_reason` populated, `llm_called=False`) when:
      - `weight <= 0.0` - feature disabled via config
      - `top_k <= 0` - no candidates would be scored
      - `candidates` is empty

    Mutates each scored candidate in place:
      - llm_topical_relevance, llm_engagement_value, llm_information_depth
      - llm_quality_score (0-1, derived)
      - heading_priority (blended: (1-w)*old + w*quality)

    Never aborts. On LLM failure, returns with `llm_failed=True` and
    leaves `heading_priority` untouched.
    """
    effective_weight = (
        weight if weight is not None
        else settings.brief_llm_scoring_weight
    )
    effective_top_k = (
        top_k if top_k is not None
        else settings.brief_llm_scoring_top_k
    )

    if effective_weight <= 0.0:
        return LLMScoringResult(skipped_reason="weight_zero")
    if effective_top_k <= 0:
        return LLMScoringResult(skipped_reason="top_k_zero")
    if not candidates:
        return LLMScoringResult(skipped_reason="empty_candidates")

    # Pick the top-K by current heading_priority (descending). Stable sort
    # preserves source order on ties so re-runs over the same input are
    # deterministic.
    sorted_indices = sorted(
        range(len(candidates)),
        key=lambda i: candidates[i].heading_priority,
        reverse=True,
    )
    top_indices = sorted_indices[:effective_top_k]
    top_candidates = [candidates[i] for i in top_indices]

    call = llm_json_fn or claude_json
    system = _SCORING_SYSTEM_PROMPT
    user = _build_user_prompt(
        keyword=keyword, title=title, intent=intent,
        candidates=top_candidates,
    )

    result = LLMScoringResult(llm_called=True)
    try:
        response = await call(system, user, max_tokens=900, temperature=0.1)
    except Exception as exc:
        result.llm_failed = True
        logger.warning(
            "brief.llm_scoring.llm_failed",
            extra={
                "intent": intent,
                "scored_window": len(top_candidates),
                "error": str(exc),
            },
        )
        return result

    raw_scores = (
        response.get("scores") if isinstance(response, dict) else None
    )
    if not isinstance(raw_scores, list):
        result.no_valid_scores = True
        logger.warning(
            "brief.llm_scoring.no_valid_scores",
            extra={"intent": intent, "scored_window": len(top_candidates)},
        )
        return result

    # Apply scores back to candidates by index.
    scored_count = 0
    priority_changed_count = 0
    for entry in raw_scores:
        if not isinstance(entry, dict):
            continue
        idx_in_window = entry.get("index")
        if (
            not isinstance(idx_in_window, int)
            or not 0 <= idx_in_window < len(top_candidates)
        ):
            continue
        topical = _clamp_score(entry.get("topical_relevance"))
        engagement = _clamp_score(entry.get("engagement_value"))
        depth = _clamp_score(entry.get("information_depth"))
        if topical is None or engagement is None or depth is None:
            continue

        cand = top_candidates[idx_in_window]
        cand.llm_topical_relevance = topical
        cand.llm_engagement_value = engagement
        cand.llm_information_depth = depth
        cand.llm_quality_score = _normalize_quality(topical, engagement, depth)

        # Blend: (1 - weight) * vector + weight * llm
        old_priority = cand.heading_priority
        new_priority = (
            (1.0 - effective_weight) * old_priority
            + effective_weight * cand.llm_quality_score
        )
        cand.heading_priority = new_priority
        scored_count += 1
        if abs(new_priority - old_priority) > 1e-9:
            priority_changed_count += 1

    if scored_count == 0:
        result.no_valid_scores = True
        logger.warning(
            "brief.llm_scoring.no_valid_scores",
            extra={
                "intent": intent,
                "scored_window": len(top_candidates),
                "raw_scores_count": len(raw_scores),
            },
        )
        return result

    result.scored_count = scored_count
    result.priority_changed_count = priority_changed_count
    result.score_distribution = _distribution_summary(top_candidates)

    logger.info(
        "brief.llm_scoring.complete",
        extra={
            "intent": intent,
            "scored_window": len(top_candidates),
            "scored_count": scored_count,
            "priority_changed_count": priority_changed_count,
            "weight": effective_weight,
            **result.score_distribution,
        },
    )
    return result
