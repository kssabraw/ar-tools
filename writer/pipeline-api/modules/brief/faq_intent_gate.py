"""Step 10.5 - FAQ Intent Gate (Brief Generator PRD v2.2 / Phase 2).

Catches FAQs that are topically related to the keyword but represent a
DIFFERENT stakeholder's question. The audit example: a seller-ROI
article keyword shipped FAQs about creator-monetization because the
underlying SERP/Reddit pool surfaced both stakeholder voices and the
top-by-search-volume FAQs leaked across cohorts.

Two-stage gate:

  1. Cosine floor against an `intent_profile` vector built from
     `intent_type + title + scope_statement + persona.primary_goal`.
     FAQs scoring below `INTENT_FLOOR` (default 0.55) are dropped with
     `discard_reason="faq_intent_mismatch"` BEFORE the LLM call.
  2. Single batched Claude call over the cosine-floor survivors:
     classify each as `matches_primary_intent` / `adjacent_intent` /
     `different_audience`. `different_audience` candidates are dropped
     with the same discard reason.

Relaxation: if fewer than `MIN_FAQ_FLOOR` (3) `matches_primary_intent`
candidates survive both gates, fall back to keeping the highest-scoring
`adjacent_intent` survivors until the count reaches 3, with
`metadata.faq_intent_gate_relaxation_applied = true`. If still under
3 (e.g. tiny pool), accept whatever survives.

Failure handling:
  - Embedding API call fails → log + skip the gate entirely; flag the
    fallback in the result.
  - LLM call fails (after one retry) → keep all cosine-floor survivors;
    treat each as `matches_primary_intent` for accounting purposes;
    flag fallback. Run continues normally.

This module mutates the input candidate list - both kept and rejected
candidates retain their FAQCandidate objects, but rejected ones are
appended to `rejected` and excluded from `kept`. The faq_score is
NOT recomputed here; that's the responsibility of `score_faqs` upstream
(which now uses an intent-aware semantic_score per Phase 2).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .faqs import FAQCandidate
from .llm import claude_json, embed_batch_large

logger = logging.getLogger(__name__)


INTENT_FLOOR = 0.55
MIN_FAQ_FLOOR = 3  # match faqs.MIN_FAQS_FALLBACK
VALID_INTENT_ROLES = frozenset({
    "matches_primary_intent", "adjacent_intent", "different_audience",
})

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]
LLMJsonFn = Callable[..., Awaitable[Any]]


SYSTEM_PROMPT = """\
You audit FAQs for an SEO blog brief. Each FAQ is a question that might
appear in the article's FAQ section. Your job: confirm each FAQ aligns
with the article's PRIMARY stakeholder/intent, not an adjacent
stakeholder who happens to share keyword surface area.

Example failure mode: an article about increasing ROI for TikTok Shop
SELLERS has FAQs about CREATOR monetization mixed in. Both touch
TikTok, but the seller-ROI reader doesn't want creator-monetization
guidance - that's a different stakeholder's question.

Classifications:
  - "matches_primary_intent": FAQ aligns with the persona's primary
    goal and the title's intent (the expected case).
  - "adjacent_intent": FAQ is on-topic but represents a different
    stakeholder question. Acceptable as filler if there aren't enough
    matches_primary_intent candidates, but not preferred.
  - "different_audience": FAQ targets a different stakeholder entirely
    (e.g. creator-monetization on a seller-ROI article). Drop.

Output strict JSON only - no preamble, no markdown fences:
{
  "verifications": [
    {
      "faq_id": "<exact id from input>",
      "intent_role": "matches_primary_intent" | "adjacent_intent" | "different_audience",
      "reasoning": "≤200 chars: which stakeholder this FAQ targets"
    }
  ]
}

You MUST classify every FAQ in the input, returning the same faq_id."""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response was rejected. Output ONLY the JSON
object. Each entry MUST carry faq_id (a short identifier from the
input), intent_role (one of: matches_primary_intent, adjacent_intent,
different_audience), and a brief reasoning."""


@dataclass
class FAQIntentGateResult:
    """Output of `apply_faq_intent_gate`."""

    kept: list[FAQCandidate] = field(default_factory=list)
    # Per-kept embedding, parallel to `kept`. Phase 2 review fix #6:
    # exposed so the pipeline can pass them into `score_faqs` and
    # avoid a second embedding API call. Empty list when the gate
    # was skipped (embed fallback) or when `kept` is empty.
    kept_embeddings: list[list[float]] = field(default_factory=list)
    rejected: list[FAQCandidate] = field(default_factory=list)
    floor_rejected_count: int = 0
    llm_rejected_count: int = 0
    relaxation_applied: bool = False
    # Phase 2 review fix #4 - when the gate would otherwise produce zero
    # kept on a non-empty input pool (every candidate failed both
    # cosine floor AND any LLM filter), the gate falls back to the
    # original pool to honor PRD §5 Step 10's 3–5 FAQ guarantee.
    full_relaxation_applied: bool = False
    intent_profile_text: str = ""
    intent_profile_embedding: list[float] = field(default_factory=list)
    fallback_embed_applied: bool = False
    fallback_llm_applied: bool = False


def build_intent_profile_text(
    *,
    intent_type: str,
    title: str,
    scope_statement: str,
    persona_primary_goal: str = "",
) -> str:
    """Compose the natural-language intent profile fed to the embedding
    model. We include persona.primary_goal because it captures the
    stakeholder framing (the audit failure case turned on
    seller-vs-creator phrasing - `persona.primary_goal` is the
    cleanest signal of which stakeholder the article targets).
    """
    parts = [
        f"Article intent: {intent_type}.",
        f"Title: {title}.",
        f"Scope: {scope_statement}",
    ]
    if persona_primary_goal:
        parts.append(f"Reader's primary goal: {persona_primary_goal}")
    return " ".join(p.strip() for p in parts if p.strip())


def _cosine_unit(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


async def embed_intent_profile(
    profile_text: str,
    *,
    embed_fn: Optional[EmbedFn] = None,
) -> list[float]:
    """Embed the intent profile string as a single unit-normalized
    vector. Returns [] on failure (caller treats as "skip the gate")."""
    if not profile_text.strip():
        return []
    fn = embed_fn or embed_batch_large
    try:
        embeddings = await fn([profile_text])
        if embeddings and embeddings[0]:
            return embeddings[0]
    except Exception as exc:
        logger.warning(
            "brief.faq_intent_gate.embed_failed",
            extra={"error": str(exc)},
        )
    return []


def apply_cosine_floor(
    candidates: list[FAQCandidate],
    intent_profile_embedding: list[float],
    faq_embeddings: list[list[float]],
    *,
    floor: float = INTENT_FLOOR,
) -> tuple[
    list[FAQCandidate],
    list[list[float]],
    list[FAQCandidate],
]:
    """Pure-CPU floor pass. Returns (survivors, survivor_embeddings,
    rejected).

    Stamps `intent_profile_cosine` on every candidate (survivors and
    rejects) so the relaxation path can rank `adjacent_intent`
    candidates by intent alignment without re-computing - Phase 2
    review fix #3.

    Returns the survivors' embeddings parallel to `survivors` so
    callers can hand them downstream to `score_faqs` without a second
    embedding API call - Phase 2 review fix #6.

    A candidate's `faq_score` is NOT recomputed here - only the floor
    decision. Callers are expected to compute faq_score via
    `faqs.score_faqs` after the gate runs (the gate result carries the
    embeddings to enable that).
    """
    survivors: list[FAQCandidate] = []
    survivor_embeddings: list[list[float]] = []
    rejected: list[FAQCandidate] = []
    for c, vec in zip(candidates, faq_embeddings):
        alignment = _cosine_unit(intent_profile_embedding, vec)
        c.intent_profile_cosine = alignment  # type: ignore[assignment]
        if alignment < floor:
            rejected.append(c)
            logger.debug(
                "brief.faq_intent_gate.floor_rejected",
                extra={
                    "question": c.question,
                    "alignment": round(alignment, 4),
                    "floor": floor,
                },
            )
        else:
            survivors.append(c)
            survivor_embeddings.append(vec)
    return survivors, survivor_embeddings, rejected


def _format_user_prompt(
    intent_profile_text: str,
    candidates: list[FAQCandidate],
) -> tuple[str, dict[str, FAQCandidate]]:
    payload: list[dict[str, str]] = []
    by_id: dict[str, FAQCandidate] = {}
    for i, c in enumerate(candidates):
        faq_id = f"faq_{i}"
        by_id[faq_id] = c
        payload.append({"faq_id": faq_id, "question": c.question})
    user = (
        f"Intent profile:\n{intent_profile_text}\n\n"
        f"FAQs to verify (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
    )
    return user, by_id


def _validate_payload(
    payload: Any,
    by_id: dict[str, FAQCandidate],
) -> tuple[bool, str, Optional[dict[str, str]]]:
    if not isinstance(payload, dict):
        return False, "payload_not_object", None
    verifications = payload.get("verifications")
    if not isinstance(verifications, list):
        return False, "verifications_not_list", None
    classifications: dict[str, str] = {}
    for entry in verifications:
        if not isinstance(entry, dict):
            continue
        faq_id = entry.get("faq_id")
        role = entry.get("intent_role")
        if not isinstance(faq_id, str) or faq_id not in by_id:
            logger.warning(
                "brief.faq_intent_gate.rogue_id",
                extra={"faq_id": faq_id, "role": role},
            )
            continue
        if role not in VALID_INTENT_ROLES:
            continue
        classifications[faq_id] = role
    if not classifications:
        return False, "no_valid_classifications", None
    return True, "ok", classifications


async def apply_faq_intent_gate(
    candidates: list[FAQCandidate],
    *,
    intent_type: str,
    title: str,
    scope_statement: str,
    persona_primary_goal: str = "",
    floor: float = INTENT_FLOOR,
    min_faq_floor: int = MIN_FAQ_FLOOR,
    embed_fn: Optional[EmbedFn] = None,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> FAQIntentGateResult:
    """Run the two-stage gate. Returns a FAQIntentGateResult; the kept
    list is what should flow into `select_faqs`.

    Empty input → empty result, no calls.
    """
    result = FAQIntentGateResult()
    if not candidates:
        return result

    profile_text = build_intent_profile_text(
        intent_type=intent_type,
        title=title,
        scope_statement=scope_statement,
        persona_primary_goal=persona_primary_goal,
    )
    result.intent_profile_text = profile_text

    profile_embedding = await embed_intent_profile(
        profile_text, embed_fn=embed_fn,
    )
    if not profile_embedding:
        # Skip the gate entirely; flag fallback so consumers can see it.
        logger.warning(
            "brief.faq_intent_gate.embed_skipped",
            extra={"candidate_count": len(candidates)},
        )
        result.fallback_embed_applied = True
        result.kept = list(candidates)
        return result

    result.intent_profile_embedding = profile_embedding

    fn = embed_fn or embed_batch_large
    try:
        faq_embeddings = await fn([c.question for c in candidates])
    except Exception as exc:
        logger.warning(
            "brief.faq_intent_gate.faq_embed_failed",
            extra={"error": str(exc)},
        )
        result.fallback_embed_applied = True
        result.kept = list(candidates)
        # No embeddings to expose; score_faqs will re-embed (acceptable
        # under fallback - embed outage isn't a steady state).
        return result

    survivors, survivor_embeddings, floor_rejected = apply_cosine_floor(
        candidates, profile_embedding, faq_embeddings, floor=floor,
    )
    result.floor_rejected_count = len(floor_rejected)
    result.rejected.extend(floor_rejected)

    if not survivors:
        # Phase 2 review fix #4 - every candidate failed the cosine
        # floor. PRD §5 Step 10 promises 3–5 FAQs always, so falling
        # back to an empty FAQ section regresses on a stronger
        # guarantee. Re-admit the original pool with intent_role=
        # "adjacent_intent" so consumers can highlight the full-
        # relaxation case for review.
        if not candidates:
            return result
        for c in candidates:
            c.intent_role = "adjacent_intent"  # type: ignore[assignment]
        result.kept = list(candidates)
        result.kept_embeddings = list(faq_embeddings)
        result.full_relaxation_applied = True
        # The candidates are no longer in `result.rejected` - the floor
        # rejection was overturned by the full-relaxation fallback.
        result.rejected = []
        result.floor_rejected_count = 0
        logger.warning(
            "brief.faq_intent_gate.full_relaxation",
            extra={
                "fallback": "accept_all_as_adjacent_intent",
                "candidate_count": len(candidates),
            },
        )
        return result

    # ---- Stage 2: LLM intent-role classifier on survivors ----
    # Map id → (FAQCandidate, embedding) so we can carry embeddings
    # forward into the kept list (Phase 2 review fix #6).
    survivor_embedding_by_id: dict[str, list[float]] = {}
    call = llm_json_fn or claude_json
    user, by_id = _format_user_prompt(profile_text, survivors)
    for (faq_id, c), vec in zip(by_id.items(), survivor_embeddings):
        survivor_embedding_by_id[faq_id] = vec
    classifications: Optional[dict[str, str]] = None
    last_error = "unknown"

    for attempt in (1, 2):
        system = (
            SYSTEM_PROMPT if attempt == 1
            else SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX
        )
        try:
            payload = await call(
                system, user,
                max_tokens=1500,
                temperature=0.2 if attempt == 1 else 0.1,
            )
        except Exception as exc:
            last_error = f"llm_call_exception: {exc}"
            logger.warning(
                "brief.faq_intent_gate.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue
        ok, reason, parsed = _validate_payload(payload, by_id)
        if ok and parsed is not None:
            classifications = parsed
            break
        last_error = reason
        logger.warning(
            "brief.faq_intent_gate.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    if classifications is None:
        # LLM unavailable → keep every survivor as primary_intent. The
        # cosine floor already filtered the egregious cases; the LLM
        # was a refinement.
        logger.warning(
            "brief.faq_intent_gate.llm_fallback",
            extra={
                "reason": last_error,
                "fallback": "accept_all_as_matches_primary_intent",
            },
        )
        result.fallback_llm_applied = True
        for c in survivors:
            c.intent_role = "matches_primary_intent"  # type: ignore[assignment]
        result.kept = list(survivors)
        result.kept_embeddings = list(survivor_embeddings)
        return result

    primary: list[FAQCandidate] = []
    primary_embeddings: list[list[float]] = []
    adjacent: list[FAQCandidate] = []
    adjacent_embeddings: list[list[float]] = []
    different: list[FAQCandidate] = []

    for faq_id, c in by_id.items():
        role = classifications.get(faq_id, "matches_primary_intent")
        emb = survivor_embedding_by_id.get(faq_id, [])
        if role == "matches_primary_intent":
            c.intent_role = "matches_primary_intent"  # type: ignore[assignment]
            primary.append(c)
            primary_embeddings.append(emb)
        elif role == "adjacent_intent":
            c.intent_role = "adjacent_intent"  # type: ignore[assignment]
            adjacent.append(c)
            adjacent_embeddings.append(emb)
        else:  # different_audience
            different.append(c)

    result.llm_rejected_count = len(different)
    result.rejected.extend(different)

    # Phase 2 review fix #3 - sort adjacent candidates by their cached
    # `intent_profile_cosine` (stamped during apply_cosine_floor), NOT
    # by `faq_score`, which is 0.0 for every candidate at this point
    # because `score_faqs` runs after the gate. Higher cosine to the
    # intent profile = "least off-topic among the adjacent" = best
    # relaxation fallback.
    if len(primary) < min_faq_floor and adjacent:
        adjacent_paired = sorted(
            zip(adjacent, adjacent_embeddings),
            key=lambda pair: pair[0].intent_profile_cosine,
            reverse=True,
        )
        needed = min_faq_floor - len(primary)
        kept_adjacent_pairs = adjacent_paired[:needed]
        result.kept = primary + [p[0] for p in kept_adjacent_pairs]
        result.kept_embeddings = primary_embeddings + [p[1] for p in kept_adjacent_pairs]
        result.relaxation_applied = True
        # Adjacent candidates not promoted into kept are still
        # informative for the consumer (they were classified, just not
        # needed); rejected list intentionally excludes them so the
        # rejected count reflects only LLM-filtered different_audience.
    else:
        result.kept = primary
        result.kept_embeddings = primary_embeddings
        # Adjacent candidates that didn't survive ARE included in
        # `rejected` so downstream metadata reflects the LLM filter.
        result.rejected.extend(adjacent)

    # Phase 2 review fix #4 - even after the LLM stage, kept might be
    # empty (everyone different_audience, or LLM filtered everything).
    # Honor the 3–5 FAQ guarantee by full-relaxing on the original pool.
    if not result.kept and candidates:
        for c in candidates:
            c.intent_role = "adjacent_intent"  # type: ignore[assignment]
        result.kept = list(candidates)
        result.kept_embeddings = list(faq_embeddings)
        result.full_relaxation_applied = True
        # Reset bookkeeping that no longer reflects reality.
        result.rejected = []
        result.floor_rejected_count = 0
        result.llm_rejected_count = 0
        logger.warning(
            "brief.faq_intent_gate.full_relaxation",
            extra={
                "fallback": "accept_all_as_adjacent_intent",
                "candidate_count": len(candidates),
                "stage": "post_llm",
            },
        )

    logger.info(
        "brief.faq_intent_gate.complete",
        extra={
            "input_count": len(candidates),
            "floor_rejected": result.floor_rejected_count,
            "llm_rejected": result.llm_rejected_count,
            "primary_kept": len(primary),
            "adjacent_kept_via_relaxation": (
                max(0, len(result.kept) - len(primary))
            ),
            "relaxation_applied": result.relaxation_applied,
            "full_relaxation_applied": result.full_relaxation_applied,
        },
    )
    return result
