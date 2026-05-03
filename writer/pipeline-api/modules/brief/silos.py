"""Step 12 — Silo Cluster Identification (Brief Generator v2.0.2).

Implements PRD §5 Step 12.1–12.6. Reuses regions from Step 5 — zero
additional embedding or clustering cost over what's already been
computed. Adds three layers of refinement so the silo output is a
prioritized roadmap rather than a noisy list:

  12.1 Discard-reason filtering (which discarded headings can become silo material)
  12.2 Cluster formation (region reuse + coherence + centroid keyword)
  12.3 Search-demand validation (five-signal demand score, hard floor 0.30)
  12.4 Independent article viability check (parallel LLM call)
  12.5 Cross-brief deduplication (DEFERRED to v2.1 — count defaults to 1)
  12.6 Output format (carries discard_reason_breakdown + demand + viability)

Step 12.4 is async and lives in `verify_silo_viability` so the
orchestrator can run viability checks for every silo concurrently with
`asyncio.gather`. Steps 12.1–12.3 are synchronous compute.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.brief import (
    IntentType,
    SiloCandidate,
    SiloSourceHeading,
)

from .graph import Candidate, RegionInfo
from .llm import claude_json

logger = logging.getLogger(__name__)


MIN_HEADINGS_PER_CLUSTER = 2
MIN_CLUSTER_COHERENCE = 0.60
REVIEW_RECOMMENDED_MAX = 0.70
MAX_SILO_CANDIDATES = 10
SINGLETON_COHERENCE = 1.0

# PRD §5 Step 12.3 — search-demand floor
MIN_SEARCH_DEMAND_SCORE = 0.30

# PRD §5 Step 12.4 — viability LLM payload limits
MAX_VIABILITY_REASONING_LEN = 150
VALID_INTENTS: frozenset[str] = frozenset({
    "informational",
    "listicle",
    "how-to",
    "comparison",
    "ecom",
    "local-seo",
    "news",
    "informational-commercial",
})


# ----------------------------------------------------------------------
# Step 12.1 — Discard-reason filtering
# ----------------------------------------------------------------------

# Discard reasons that route members into the silo pipeline. "No" reasons
# are excluded outright; "Conditional" is checked at the per-region level
# (below_priority_threshold is eligible only if the candidate's region
# did NOT contribute a selected H2).
_SILO_ELIGIBLE_REASONS_YES: frozenset[str] = frozenset({
    "scope_verification_out_of_scope",
    "global_cap_exceeded",
    # PRD v2.2 / Phase 2 — Step 8.7 outputs route via singleton paths
    # (`h3_parent_fit_rejects`) but this table stays internally consistent
    # so future cluster-aware aggregation doesn't need a second update.
    "h3_wrong_parent",
    "h3_promoted_to_h2_candidate",
})
_SILO_ELIGIBLE_REASONS_CONDITIONAL: frozenset[str] = frozenset({
    "below_priority_threshold",
})


def _is_member_eligible(
    cand: Candidate,
    *,
    region_contributed: bool,
) -> bool:
    """PRD §5 Step 12.1 — per-member eligibility check.

    Members with no `discard_reason` are eligible (they were in the pool
    but the orchestrator routed them here for cluster formation). Members
    with explicit reasons must match the eligibility table.
    """
    reason = cand.discard_reason
    if reason is None:
        return True
    if reason in _SILO_ELIGIBLE_REASONS_YES:
        return True
    if reason in _SILO_ELIGIBLE_REASONS_CONDITIONAL:
        return not region_contributed
    return False


# ----------------------------------------------------------------------
# Step 12.2 — Cluster formation helpers
# ----------------------------------------------------------------------

def _coherence(members: list[Candidate]) -> float:
    """Average pairwise cosine within a region (singletons return 0.0)."""
    if len(members) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for x in range(len(members)):
        for y in range(x + 1, len(members)):
            a = members[x].embedding
            b = members[y].embedding
            if a and b:
                total += sum(p * q for p, q in zip(a, b))
                pairs += 1
    return total / pairs if pairs else 0.0


def _centroid_heading(members: list[Candidate]) -> str:
    """Pick the heading with highest avg cosine to the rest."""
    if not members:
        return ""
    if len(members) == 1:
        return members[0].text
    best = members[0]
    best_avg = -float("inf")
    for i, c in enumerate(members):
        sims = []
        for j, other in enumerate(members):
            if i == j:
                continue
            if c.embedding and other.embedding:
                sims.append(sum(p * q for p, q in zip(c.embedding, other.embedding)))
        avg = sum(sims) / len(sims) if sims else 0.0
        if avg > best_avg:
            best_avg = avg
            best = c
    return best.text


def _infer_intent(headings: list[str]) -> IntentType:
    """Cheap heading-pattern intent inference for silo seeds. Same logic
    as the legacy v1.7 path — preserved verbatim because PRD §14.2 lists
    silo cluster quality rules as unchanged."""
    blob = " ".join(h.lower() for h in headings)
    if "vs " in blob or "versus" in blob or "comparison" in blob:
        return "comparison"
    if "how to" in blob or any(h.lower().startswith("how to") for h in headings):
        return "how-to"
    if sum(1 for h in headings if re.match(r"^\s*\d+\s+", h)) >= max(2, len(headings) // 3):
        return "listicle"
    if any(kw in blob for kw in ("best", "top", "review")):
        return "informational-commercial"
    return "informational"


def _make_source_heading(c: Candidate) -> SiloSourceHeading:
    return SiloSourceHeading(
        text=c.text,
        source=c.source,
        title_relevance=round(c.title_relevance, 4),
        heading_priority=round(c.heading_priority, 4),
        discard_reason=c.discard_reason,  # type: ignore[arg-type]
    )


def _discard_reason_breakdown(members: list[Candidate]) -> dict[str, int]:
    """Count discard_reasons among members (None values are skipped)."""
    counts: Counter[str] = Counter()
    for c in members:
        if c.discard_reason:
            counts[c.discard_reason] += 1
    return dict(counts)


# ----------------------------------------------------------------------
# Step 12.3 — Search-demand score
# ----------------------------------------------------------------------

def _search_demand_score(members: list[Candidate]) -> float:
    """PRD §5 Step 12.3 — five-signal weighted score over member metadata.

    Returns 0.0 for empty input. Each signal is normalized to [0, 1].
    """
    if not members:
        return 0.0
    max_freq = max((m.serp_frequency or 0) for m in members)
    max_consensus = max((m.llm_fanout_consensus or 0) for m in members)
    has_paa = any(m.source == "paa" for m in members)
    has_autocomplete = any(
        m.source in ("autocomplete", "keyword_suggestion") for m in members
    )
    has_reddit = any(m.source == "reddit" for m in members)

    return (
        0.30 * min(max_freq / 20.0, 1.0)
        + 0.25 * min(max_consensus / 4.0, 1.0)
        + 0.20 * (1.0 if has_paa else 0.0)
        + 0.15 * (1.0 if has_autocomplete else 0.0)
        + 0.10 * (1.0 if has_reddit else 0.0)
    )


# ----------------------------------------------------------------------
# identify_silos — orchestrates 12.1 → 12.3 (sync)
# ----------------------------------------------------------------------

@dataclass
class SiloIdentificationResult:
    """Output of `identify_silos` (Step 12.1–12.3, pre-viability).

    Each `SiloCandidate` in `candidates` carries
    `viable_as_standalone_article=True` by default; the orchestrator
    runs `verify_silo_viability` (Step 12.4) to confirm or reject and
    fill `viability_reasoning` + `estimated_intent`.

    Supports tuple unpacking `(candidates, low_coherence_candidates)`
    for backward compat with the pre-12.6 call sites.
    """
    candidates: list[SiloCandidate] = field(default_factory=list)
    low_coherence_candidates: list[Candidate] = field(default_factory=list)
    rejected_by_discard_reason_count: int = 0
    rejected_by_search_demand_count: int = 0

    def __iter__(self):
        yield self.candidates
        yield self.low_coherence_candidates


def identify_silos(
    *,
    regions: list[RegionInfo],
    candidate_pool: list[Candidate],
    contributing_region_ids: set[str],
    scope_rejects: list[Candidate],
    h3_scope_rejects: Optional[list[Candidate]] = None,
    relevance_rejects: Optional[list[Candidate]] = None,
    h3_parent_fit_rejects: Optional[list[Candidate]] = None,
    min_coherence: float = MIN_CLUSTER_COHERENCE,
    review_threshold: float = REVIEW_RECOMMENDED_MAX,
    max_candidates: int = MAX_SILO_CANDIDATES,
    min_search_demand: float = MIN_SEARCH_DEMAND_SCORE,
) -> SiloIdentificationResult:
    """Build silo candidates from non-contributing regions + scope rejects.

    Pipeline:
      Step 12.1: filter member candidates by discard_reason eligibility
      Step 12.2: form clusters / singletons + score coherence
      Step 12.3: drop clusters whose search_demand_score < min_search_demand

    Returns a `SiloIdentificationResult` whose `candidates` are pre-
    viability — the orchestrator runs `verify_silo_viability` on them
    next to apply Step 12.4.
    """
    silos_with_score: list[tuple[float, SiloCandidate]] = []
    low_coherence: list[Candidate] = []
    rejected_discard = 0
    rejected_demand = 0

    # ---- non-selected, non-eliminated regions ----
    for region in regions:
        if region.eliminated:
            continue
        region_contributed = region.region_id in contributing_region_ids
        if region_contributed:
            # Members of contributing regions can still be eligible for
            # silos via their discard reason ("Yes — global_cap_exceeded"),
            # but we'd treat them as singletons; the cluster path is for
            # non-contributing regions only.
            continue

        # 12.1 — filter members
        all_members = [candidate_pool[i] for i in region.member_indices]
        eligible_members = [
            c for c in all_members
            if _is_member_eligible(c, region_contributed=False)
        ]
        rejected_discard += len(all_members) - len(eligible_members)

        if len(eligible_members) < MIN_HEADINGS_PER_CLUSTER:
            continue

        # 12.2 — coherence + centroid
        coh = _coherence(eligible_members)
        if coh < min_coherence:
            for cand in eligible_members:
                cand.discard_reason = "low_cluster_coherence"
                low_coherence.append(cand)
            logger.info(
                "brief.silo.low_coherence",
                extra={
                    "region_id": region.region_id,
                    "coherence": round(coh, 4),
                    "threshold": min_coherence,
                    "members": len(eligible_members),
                },
            )
            continue

        # 12.3 — search demand
        demand = _search_demand_score(eligible_members)
        if demand < min_search_demand:
            rejected_demand += 1
            logger.info(
                "brief.silo.low_search_demand",
                extra={
                    "region_id": region.region_id,
                    "search_demand_score": round(demand, 4),
                    "threshold": min_search_demand,
                },
            )
            continue

        seed_text = _centroid_heading(eligible_members)
        recommended_intent = _infer_intent([c.text for c in eligible_members])
        review_recommended = coh < review_threshold

        silo = SiloCandidate(
            suggested_keyword=seed_text,
            cluster_coherence_score=round(coh, 4),
            review_recommended=review_recommended,
            recommended_intent=recommended_intent,
            routed_from="non_selected_region",
            source_headings=[_make_source_heading(c) for c in eligible_members],
            discard_reason_breakdown=_discard_reason_breakdown(eligible_members),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        silos_with_score.append((coh, silo))

    # ---- contributing-region members with global_cap_exceeded ----
    # PRD §5 Step 12.1 marks `global_cap_exceeded` as "Yes — medium
    # priority" (eligible regardless of region). When their region also
    # contributed an H2, the cluster path can't form a silo around them
    # — the H2 already won that topic. Surface them as singleton silos
    # so cut-for-length material doesn't get silently dropped.
    cluster_member_ids: set[int] = set()
    for region in regions:
        if region.region_id in contributing_region_ids:
            continue
        for idx in region.member_indices:
            cluster_member_ids.add(id(candidate_pool[idx]))

    for cand in candidate_pool:
        if cand.discard_reason != "global_cap_exceeded":
            continue
        if id(cand) in cluster_member_ids:
            # Already considered via the non-contributing-region cluster path.
            continue
        recommended_intent = _infer_intent([cand.text])
        demand = _search_demand_score([cand])
        if demand < min_search_demand:
            rejected_demand += 1
            continue
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,
            recommended_intent=recommended_intent,
            routed_from="non_selected_region",
            source_headings=[_make_source_heading(cand)],
            discard_reason_breakdown=_discard_reason_breakdown([cand]),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- scope-verification singleton rejects ----
    for cand in scope_rejects:
        if cand.discard_reason != "scope_verification_out_of_scope":
            continue
        recommended_intent = _infer_intent([cand.text])
        demand = _search_demand_score([cand])
        if demand < min_search_demand:
            rejected_demand += 1
            logger.info(
                "brief.silo.singleton_low_search_demand",
                extra={
                    "heading": cand.text,
                    "search_demand_score": round(demand, 4),
                    "threshold": min_search_demand,
                },
            )
            continue
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,
            recommended_intent=recommended_intent,
            routed_from="scope_verification",
            source_headings=[_make_source_heading(cand)],
            discard_reason_breakdown=_discard_reason_breakdown([cand]),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        # Singletons sit at the top of the priority list (coherence 1.0)
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- Authority Gap H3 scope-verification singleton rejects (PRD v2.0.3 Step 8.5b) ----
    for cand in (h3_scope_rejects or []):
        if cand.discard_reason != "scope_verification_out_of_scope":
            continue
        recommended_intent = _infer_intent([cand.text])
        demand = _search_demand_score([cand])
        if demand < min_search_demand:
            rejected_demand += 1
            logger.info(
                "brief.silo.h3_singleton_low_search_demand",
                extra={
                    "heading": cand.text,
                    "search_demand_score": round(demand, 4),
                    "threshold": min_search_demand,
                },
            )
            continue
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,
            recommended_intent=recommended_intent,
            routed_from="scope_verification_h3",
            source_headings=[_make_source_heading(cand)],
            discard_reason_breakdown=_discard_reason_breakdown([cand]),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- Step 5.1 relevance-floor singletons ----
    # Headings discarded as below_relevance_floor are below the title's
    # relevance floor (so excluded from the parent article) but often
    # represent adjacent topics. Without this path, runs whose SERP is
    # dominated by restatement clusters produce zero silos every time —
    # observed empirically on "what is a tiktok shop" and similar
    # broad-overview keywords. Search-demand floor + Step 12.4 viability
    # LLM keep noise out of the surfaced set.
    for cand in (relevance_rejects or []):
        if cand.discard_reason != "below_relevance_floor":
            continue
        recommended_intent = _infer_intent([cand.text])
        demand = _search_demand_score([cand])
        if demand < min_search_demand:
            rejected_demand += 1
            logger.info(
                "brief.silo.relevance_singleton_low_search_demand",
                extra={
                    "heading": cand.text,
                    "search_demand_score": round(demand, 4),
                    "threshold": min_search_demand,
                },
            )
            continue
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,
            recommended_intent=recommended_intent,
            routed_from="relevance_floor_reject",
            source_headings=[_make_source_heading(cand)],
            discard_reason_breakdown=_discard_reason_breakdown([cand]),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- Phase 2 / PRD v2.2 — Step 8.7 H3 parent-fit rejects ----
    # H3s the LLM classified as `wrong_parent` (no fitting parent
    # available) or `promote_to_h2` (substantial standalone topic) are
    # routed to silos as singletons with their own routed_from value so
    # the silo dashboard can highlight them as parent-fit failures.
    for cand in (h3_parent_fit_rejects or []):
        reason = cand.discard_reason
        if reason == "h3_wrong_parent":
            routed_from = "h3_parent_mismatch"
        elif reason == "h3_promoted_to_h2_candidate":
            routed_from = "h3_promote_candidate"
        else:
            continue
        recommended_intent = _infer_intent([cand.text])
        demand = _search_demand_score([cand])
        if demand < min_search_demand:
            rejected_demand += 1
            logger.info(
                "brief.silo.h3_parent_fit_low_search_demand",
                extra={
                    "heading": cand.text,
                    "routed_from": routed_from,
                    "search_demand_score": round(demand, 4),
                    "threshold": min_search_demand,
                },
            )
            continue
        silo = SiloCandidate(
            suggested_keyword=cand.text,
            cluster_coherence_score=SINGLETON_COHERENCE,
            review_recommended=False,
            recommended_intent=recommended_intent,
            routed_from=routed_from,  # type: ignore[arg-type]
            source_headings=[_make_source_heading(cand)],
            discard_reason_breakdown=_discard_reason_breakdown([cand]),
            search_demand_score=round(demand, 4),
            estimated_intent=recommended_intent,
        )
        silos_with_score.append((SINGLETON_COHERENCE, silo))

    # ---- cap at max_candidates by descending coherence ----
    silos_with_score.sort(key=lambda x: x[0], reverse=True)
    selected = [s for _, s in silos_with_score[:max_candidates]]

    logger.info(
        "brief.silo.identification_complete",
        extra={
            "input_region_count": len(regions),
            "contributing_region_count": len(contributing_region_ids),
            "scope_reject_count": len(scope_rejects),
            "low_coherence_dropped": len(low_coherence),
            "rejected_by_discard_reason": rejected_discard,
            "rejected_by_search_demand": rejected_demand,
            "candidates_pre_viability": len(selected),
        },
    )
    return SiloIdentificationResult(
        candidates=selected,
        low_coherence_candidates=low_coherence,
        rejected_by_discard_reason_count=rejected_discard,
        rejected_by_search_demand_count=rejected_demand,
    )


# ----------------------------------------------------------------------
# Step 12.4 — Viability check (async)
# ----------------------------------------------------------------------

VIABILITY_SYSTEM_PROMPT = """\
You verify whether a candidate silo keyword would make a defensible
standalone article — distinct from the parent article it was rejected
from, and substantive enough to support its own outline.

Inputs:
- The parent brief's title and scope_statement (anchors what the parent
  is committed to delivering)
- A candidate keyword that was discarded from the parent for one of
  several reasons (paraphrased the parent, fell outside scope, lost the
  H2 selection competition, or was cut for length)
- The candidate's member headings (text fragments other articles or
  searchers used for this topic)

Output strict JSON only — no preamble, no markdown fences:
{
  "candidate_keyword": "string (must match the input candidate keyword)",
  "viable_as_standalone_article": true | false,
  "reasoning": "string ≤150 chars",
  "estimated_intent": "informational | listicle | how-to | comparison | ecom | local-seo | news | informational-commercial"
}

Mark viable_as_standalone_article=true when the candidate:
- Answers a genuinely different reader question than the parent's title
- Has enough scope to support a 1500-2500 word article
- Wouldn't cannibalize the parent article's intent

Mark false when the candidate:
- Restates or mostly overlaps with the parent's intent
- Is a thin spin-off that would only support a few hundred words
- Targets the same reader question with a slight reframing

Be conservative: when ambiguous, default to true. The brief's silo
roadmap is downstream of human review.
"""


VIABILITY_RETRY_SUFFIX = """\

CRITICAL: Your previous response was rejected for a validation failure.
Output ONLY the JSON object with all four fields, no surrounding text.
"""


LLMJsonFn = Callable[..., Awaitable[Any]]


@dataclass
class SiloViabilityResult:
    """Output of `verify_silo_viability` (Step 12.4)."""
    candidates: list[SiloCandidate] = field(default_factory=list)
    rejected_count: int = 0
    fallback_applied: bool = False


def _format_viability_user_prompt(
    silo: SiloCandidate,
    title: str,
    scope_statement: str,
) -> str:
    member_lines = "\n".join(
        f"  - {h.text}" for h in silo.source_headings[:8]
    ) or "  (none)"
    return (
        f"Parent brief title:\n{title}\n\n"
        f"Parent brief scope statement:\n{scope_statement}\n\n"
        f"Candidate keyword: {silo.suggested_keyword}\n"
        f"Recommended intent (from heading patterns): {silo.recommended_intent}\n\n"
        f"Member headings:\n{member_lines}"
    )


def _validate_viability_payload(
    payload: Any,
    expected_keyword: str,
) -> tuple[bool, str, Optional[dict]]:
    """Validate one LLM viability response. Returns (ok, reason, parsed)."""
    if not isinstance(payload, dict):
        return False, "payload_not_object", None
    cand_kw = payload.get("candidate_keyword")
    if not isinstance(cand_kw, str) or not cand_kw.strip():
        return False, "candidate_keyword_missing", None
    viable = payload.get("viable_as_standalone_article")
    if not isinstance(viable, bool):
        return False, "viable_field_not_bool", None
    reason = payload.get("reasoning", "")
    if not isinstance(reason, str):
        reason = ""
    intent = payload.get("estimated_intent")
    if intent not in VALID_INTENTS:
        return False, "estimated_intent_invalid", None
    return True, "ok", {
        "viable": viable,
        "reasoning": reason.strip()[:MAX_VIABILITY_REASONING_LEN],
        "intent": intent,
    }


async def _viability_check_one(
    silo: SiloCandidate,
    title: str,
    scope_statement: str,
    call: LLMJsonFn,
) -> tuple[SiloCandidate, bool, bool]:
    """Run viability check for a single silo candidate.

    Returns (silo, was_viable, fallback_applied). The silo is mutated
    in place: viability_reasoning + estimated_intent are filled, and
    viable_as_standalone_article is set per the LLM verdict.

    On double LLM failure, defaults `viable_as_standalone_article=True`
    with a fallback flag — never aborts the run.
    """
    user = _format_viability_user_prompt(silo, title, scope_statement)
    last_error = "unknown"

    for attempt in (1, 2):
        system = (
            VIABILITY_SYSTEM_PROMPT
            if attempt == 1
            else VIABILITY_SYSTEM_PROMPT + VIABILITY_RETRY_SUFFIX
        )
        try:
            payload = await call(
                system, user,
                max_tokens=500,
                temperature=0.2 if attempt == 1 else 0.1,
            )
        except Exception as exc:
            last_error = f"llm_call_exception: {exc}"
            logger.warning(
                "brief.silo.viability_llm_failed",
                extra={
                    "candidate_keyword": silo.suggested_keyword,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            continue

        ok, reason, parsed = _validate_viability_payload(
            payload, silo.suggested_keyword,
        )
        if ok and parsed is not None:
            silo.viable_as_standalone_article = bool(parsed["viable"])
            silo.viability_reasoning = parsed["reasoning"]
            silo.estimated_intent = parsed["intent"]  # type: ignore[assignment]
            return silo, silo.viable_as_standalone_article, False

        last_error = reason
        logger.warning(
            "brief.silo.viability_invalid",
            extra={
                "candidate_keyword": silo.suggested_keyword,
                "attempt": attempt,
                "reason": reason,
            },
        )

    # Double failure → fallback to viable=True
    silo.viable_as_standalone_article = True
    silo.viability_reasoning = f"fallback_after_llm_failure: {last_error}"
    silo.estimated_intent = silo.recommended_intent
    logger.warning(
        "brief.silo.viability_fallback",
        extra={
            "candidate_keyword": silo.suggested_keyword,
            "reason": last_error,
        },
    )
    return silo, True, True


async def verify_silo_viability(
    candidates: list[SiloCandidate],
    *,
    title: str,
    scope_statement: str,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> SiloViabilityResult:
    """Step 12.4 — verify each silo candidate's standalone viability.

    Runs every candidate's check concurrently via `asyncio.gather`, so
    the wall-clock cost is one LLM round-trip regardless of count.

    Mutates each input `SiloCandidate` in place:
      - `viable_as_standalone_article` set to LLM verdict
      - `viability_reasoning` filled
      - `estimated_intent` set from LLM (overrides the heuristic
        `recommended_intent` from Step 12.2 if they disagree)

    Returns a `SiloViabilityResult` containing only the candidates that
    were verified viable, plus the count of rejects and a flag for
    whether any candidate hit the fallback path.
    """
    if not candidates:
        return SiloViabilityResult()

    call = llm_json_fn or claude_json
    results = await asyncio.gather(
        *(_viability_check_one(s, title, scope_statement, call) for s in candidates),
        return_exceptions=False,
    )

    viable: list[SiloCandidate] = []
    rejected = 0
    fallback_any = False
    for silo, was_viable, fallback in results:
        if fallback:
            fallback_any = True
        if was_viable:
            viable.append(silo)
        else:
            rejected += 1

    logger.info(
        "brief.silo.viability_complete",
        extra={
            "input_count": len(candidates),
            "viable_count": len(viable),
            "rejected_count": rejected,
            "fallback_applied": fallback_any,
        },
    )
    return SiloViabilityResult(
        candidates=viable,
        rejected_count=rejected,
        fallback_applied=fallback_any,
    )
