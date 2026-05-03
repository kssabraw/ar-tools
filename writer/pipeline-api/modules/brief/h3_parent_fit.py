"""Step 8.7 — H3 Parent-Fit Verification (Brief Generator PRD v2.2 / Phase 2).

Catches H3s that pass Step 8.6's numerical filters (parent_relevance in
[0.65, 0.85], same region as parent H2) but answer a different reader
question than the parent H2 commits to. The audited "affiliate vetting
under cart-abandonment H2" case made it through Step 8.6's bands; the
LLM classification here distinguishes "near-topic" from "actually
belongs under this H2".

This is the H3-level analogue of Step 8.5 (scope verification for H2s).
Step 8.5b already covered authority-gap H3s vs the article scope; Step
8.7 covers the H2↔H3 parent-fit relationship for ALL H3s in the final
attachment map (Step 8.6 selections + authority-gap survivors).

Inputs:
  - h2_attachments: dict[int, list[Candidate]] — final per-H2 attachment
    map after Step 8.6 + Step 9 + auth_attach. Mutated in place.
  - selected_h2s: list[Candidate] — the parent H2 list (indices align
    with attachment dict keys).

Output (FitVerificationResult):
  - reattached: list of (old_h2_idx, new_h2_idx, candidate) for H3s
    moved to a different parent based on `wrong_parent` classification
  - routed_to_silos: list of Candidates discarded for silo promotion
    (with discard_reason stamped: "h3_wrong_parent" or
    "h3_promoted_to_h2_candidate")
  - marginal_count / wrong_parent_count / promoted_count for metadata
  - fallback_applied: True when both LLM attempts failed and we
    accepted every H3 as `good`

Routing rules (per the proposal accepted alongside Phase 1):
  - good          → keep under current parent (no metadata flag)
  - marginal      → keep + stamp parent_fit_classification="marginal"
  - wrong_parent  → re-attach to highest-cosine OTHER selected H2 with
                    capacity (≤ 2 H3s, OR ≤ 3 if authority-overflow);
                    if no H2 has capacity / passes parent_relevance
                    floor, route to silos with
                    discard_reason="h3_wrong_parent"
  - promote_to_h2 → discard, route to silos with
                    discard_reason="h3_promoted_to_h2_candidate"

Authority gap H3s (`source == "authority_gap_sme"`) are never discarded
per PRD §5 Step 9 — for them, `wrong_parent` triggers re-attachment but
`promote_to_h2` is downgraded to `marginal` (kept under current parent
with the flag).

Failure handling (matches Step 8.5 / 8.5b conventions):
  - Malformed JSON → one retry with a stricter prompt
  - On second failure → accept ALL H3s as `good`; log warning and stamp
    fallback_applied=True. Never aborts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


VALID_FIT_CLASSIFICATIONS = frozenset({
    "good", "marginal", "wrong_parent", "promote_to_h2",
})

LLMJsonFn = Callable[..., Awaitable[Any]]


def _cosine_unit(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


@dataclass
class FitVerificationResult:
    """Output of `verify_h3_parent_fit`."""

    reattached: list[tuple[int, int, Candidate]] = field(default_factory=list)
    routed_to_silos: list[Candidate] = field(default_factory=list)
    marginal_count: int = 0
    wrong_parent_count: int = 0
    promoted_count: int = 0
    fallback_applied: bool = False
    llm_called: bool = False


SYSTEM_PROMPT = """\
You audit per-H2 H3 attachments in a blog brief outline. For each H3
under its parent H2, decide whether the H3 is the right kind of sub-
heading to nest beneath that H2 — not just topically related, but a
sub-question the reader would expect under that specific H2.

Examples of failure modes you should flag:
  - An H3 about "vetting affiliate partners" placed under an H2 about
    "reducing cart abandonment" — both touch e-commerce ops, but the
    H3 answers a different question.
  - An H3 that's its own substantial topic ("How algorithm signals
    weight new sellers") placed as a sub-heading instead of as a
    standalone H2.

Classifications (choose exactly one per H3):
  - "good": Belongs under this H2. The H3 answers a sub-question of
    the H2's promise.
  - "marginal": Could go either way. Reasonable readers would expect
    OR not expect this H3 under this H2. Flag for review but keep.
  - "wrong_parent": The H3 is on-topic for the article but not for THIS
    H2. It would fit better under a different H2.
  - "promote_to_h2": The H3 is substantial enough to warrant its own
    standalone article — it's not a sub-question, it's a different
    article's lead topic.

Be conservative. Default to "good" or "marginal". Only mark
"wrong_parent" or "promote_to_h2" when you can clearly state which
other H2 (or which standalone topic) the H3 belongs to.

Output strict JSON only — no preamble, no markdown fences:
{
  "verifications": [
    {
      "h3_id": "<exact id from the input>",
      "classification": "good" | "marginal" | "wrong_parent" | "promote_to_h2",
      "reasoning": "≤200 chars: why this classification"
    }
  ]
}

You MUST return one verification per input H3, with the same h3_id."""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response was rejected. Output ONLY the JSON
object with the verifications array. Each entry MUST carry h3_id (a
short string identifier from the input), classification (one of:
good, marginal, wrong_parent, promote_to_h2), and a brief reasoning."""


def _format_user_prompt(
    selected_h2s: list[Candidate],
    h2_attachments: dict[int, list[Candidate]],
) -> tuple[str, dict[str, tuple[int, int]]]:
    """Build the LLM prompt and a lookup table mapping each generated
    h3_id back to (h2_idx, list_position_under_that_h2).

    Each H3 carries a synthetic id like "h2_2.h3_0" — encodes the parent
    H2 index and the H3's position under that H2. The LLM only reads
    these as opaque tokens; the caller decodes them when applying the
    classifications.
    """
    blocks: list[dict[str, Any]] = []
    id_to_pos: dict[str, tuple[int, int]] = {}
    for h2_idx, h2 in enumerate(selected_h2s):
        attached = h2_attachments.get(h2_idx, [])
        if not attached:
            continue
        h3_entries = []
        for h3_idx, h3 in enumerate(attached):
            h3_id = f"h2_{h2_idx}.h3_{h3_idx}"
            id_to_pos[h3_id] = (h2_idx, h3_idx)
            h3_entries.append({
                "h3_id": h3_id,
                "h3_text": h3.text,
                "is_authority_gap": h3.source == "authority_gap_sme",
            })
        blocks.append({
            "h2_index": h2_idx,
            "h2_text": h2.text,
            "h3s": h3_entries,
        })
    user = (
        "Per-H2 H3 attachments to audit (JSON):\n"
        f"{json.dumps(blocks, ensure_ascii=False)}"
    )
    return user, id_to_pos


def _validate_payload(
    payload: Any,
    id_to_pos: dict[str, tuple[int, int]],
) -> tuple[bool, str, Optional[dict[str, tuple[str, str]]]]:
    if not isinstance(payload, dict):
        return False, "payload_not_object", None
    verifications = payload.get("verifications")
    if not isinstance(verifications, list):
        return False, "verifications_not_list", None
    classifications: dict[str, tuple[str, str]] = {}
    for entry in verifications:
        if not isinstance(entry, dict):
            continue
        h3_id = entry.get("h3_id")
        cls = entry.get("classification")
        reasoning = entry.get("reasoning", "") or ""
        if not isinstance(h3_id, str) or h3_id not in id_to_pos:
            logger.warning(
                "brief.h3_fit.rogue_id",
                extra={"h3_id": h3_id, "classification": cls},
            )
            continue
        if cls not in VALID_FIT_CLASSIFICATIONS:
            continue
        if not isinstance(reasoning, str):
            reasoning = ""
        classifications[h3_id] = (cls, reasoning.strip()[:200])
    if not classifications:
        return False, "no_valid_classifications", None
    return True, "ok", classifications


def _h2_capacity(
    attached: list[Candidate],
    *,
    max_h3_per_h2: int,
    authority_overflow_max: int,
) -> int:
    """Per PRD §5 Step 8.6, an H2 normally holds ≤ 2 H3s — but when
    authority-gap displacement exceeds the cap, the H2 may hold up to
    3. Use the higher cap when the H2 already holds an authority-gap
    H3 (signal that overflow happened); otherwise use the standard
    cap.
    """
    has_authority = any(c.source == "authority_gap_sme" for c in attached)
    cap = authority_overflow_max if has_authority else max_h3_per_h2
    return max(0, cap - len(attached))


def _find_better_parent(
    h3: Candidate,
    current_h2_idx: int,
    selected_h2s: list[Candidate],
    h2_attachments: dict[int, list[Candidate]],
    parent_relevance_floor: float,
    *,
    max_h3_per_h2: int,
    authority_overflow_max: int,
) -> Optional[int]:
    """Find the highest-cosine OTHER H2 that (a) has capacity and
    (b) clears the parent_relevance floor for this H3. Returns the H2
    index, or None if no candidate parent fits.
    """
    if not h3.embedding:
        return None
    best_idx: Optional[int] = None
    best_relevance = parent_relevance_floor  # require strictly above floor
    for idx, h2 in enumerate(selected_h2s):
        if idx == current_h2_idx:
            continue
        if not h2.embedding:
            continue
        capacity = _h2_capacity(
            h2_attachments.get(idx, []),
            max_h3_per_h2=max_h3_per_h2,
            authority_overflow_max=authority_overflow_max,
        )
        if capacity <= 0:
            continue
        rel = _cosine_unit(h3.embedding, h2.embedding)
        if rel > best_relevance:
            best_relevance = rel
            best_idx = idx
    return best_idx


async def verify_h3_parent_fit(
    *,
    selected_h2s: list[Candidate],
    h2_attachments: dict[int, list[Candidate]],
    parent_relevance_floor: float = 0.65,
    max_h3_per_h2: int = 2,
    authority_overflow_max: int = 3,
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> FitVerificationResult:
    """Step 8.7 — classify every H3 in `h2_attachments` and route per the
    rules in this module's docstring.

    Mutates `h2_attachments` in place:
      - good        → no change
      - marginal    → stamp `parent_fit_classification="marginal"` on the
                      candidate; remains under current parent
      - wrong_parent → moved to a different H2 (when one fits) OR
                       removed from the attachment + stamped
                       discard_reason="h3_wrong_parent" + appended to
                       routed_to_silos
      - promote_to_h2 → removed + stamped
                        discard_reason="h3_promoted_to_h2_candidate" +
                        appended to routed_to_silos
                        EXCEPT for authority-gap H3s, which downgrade
                        to "marginal" since auth H3s are never discarded.

    Empty attachments → no-op (no LLM call).
    """
    result = FitVerificationResult()
    has_any = any(h2_attachments.get(i) for i in range(len(selected_h2s)))
    if not has_any:
        return result

    user, id_to_pos = _format_user_prompt(selected_h2s, h2_attachments)
    if not id_to_pos:
        return result

    call = llm_json_fn or claude_json
    classifications: Optional[dict[str, tuple[str, str]]] = None
    last_error = "unknown"

    for attempt in (1, 2):
        result.llm_called = True
        system = (
            SYSTEM_PROMPT if attempt == 1
            else SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX
        )
        try:
            payload = await call(
                system, user,
                max_tokens=2000,
                temperature=0.2 if attempt == 1 else 0.1,
            )
        except Exception as exc:
            last_error = f"llm_call_exception: {exc}"
            logger.warning(
                "brief.h3_fit.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue
        ok, reason, parsed = _validate_payload(payload, id_to_pos)
        if ok and parsed is not None:
            classifications = parsed
            break
        last_error = reason
        logger.warning(
            "brief.h3_fit.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    if classifications is None:
        # Both attempts failed → accept everything as `good`. Don't abort.
        logger.warning(
            "brief.h3_fit.fallback",
            extra={
                "reason": last_error,
                "fallback": "accept_all_as_good",
                "attachment_count": len(id_to_pos),
            },
        )
        result.fallback_applied = True
        return result

    # Apply routing. Process H3s in deterministic order (h2 idx, h3 idx)
    # so re-attachment decisions are stable under retries.
    ordered = sorted(id_to_pos.items(), key=lambda kv: kv[1])

    for h3_id, (h2_idx, h3_idx) in ordered:
        # The attachment list may have shifted under us if a prior
        # iteration reattached an H3 to this H2 — re-resolve by lookup.
        attached = h2_attachments.get(h2_idx, [])
        if h3_idx >= len(attached):
            # Shouldn't happen, but be defensive — the LLM gave us an
            # h3_id whose original position no longer holds.
            continue
        h3 = attached[h3_idx]
        cls, _reason = classifications.get(h3_id, ("good", "default_pass"))

        if cls == "good":
            continue

        if cls == "marginal":
            h3.parent_fit_classification = "marginal"  # type: ignore[assignment]
            result.marginal_count += 1
            continue

        is_authority = h3.source == "authority_gap_sme"

        if cls == "promote_to_h2":
            if is_authority:
                # Authority-gap H3s cannot be discarded — downgrade to
                # marginal so the flag still surfaces on review.
                h3.parent_fit_classification = "marginal"  # type: ignore[assignment]
                result.marginal_count += 1
                continue
            # Remove from attachment and route to silo as standalone.
            attached.remove(h3)
            h3.discard_reason = "h3_promoted_to_h2_candidate"  # type: ignore[assignment]
            result.routed_to_silos.append(h3)
            result.promoted_count += 1
            continue

        if cls == "wrong_parent":
            new_idx = _find_better_parent(
                h3,
                current_h2_idx=h2_idx,
                selected_h2s=selected_h2s,
                h2_attachments=h2_attachments,
                parent_relevance_floor=parent_relevance_floor,
                max_h3_per_h2=max_h3_per_h2,
                authority_overflow_max=authority_overflow_max,
            )
            if new_idx is not None:
                # Re-attach to better parent.
                attached.remove(h3)
                # Refresh parent_h2_text + parent_relevance for the new parent.
                new_parent = selected_h2s[new_idx]
                h3.parent_h2_text = new_parent.text
                h3.parent_relevance = _cosine_unit(h3.embedding, new_parent.embedding)
                h2_attachments.setdefault(new_idx, []).append(h3)
                result.reattached.append((h2_idx, new_idx, h3))
                result.wrong_parent_count += 1
                continue
            # No fitting parent — route to silo (unless authority-gap,
            # which downgrades to marginal under current parent).
            if is_authority:
                h3.parent_fit_classification = "marginal"  # type: ignore[assignment]
                result.marginal_count += 1
                continue
            attached.remove(h3)
            h3.discard_reason = "h3_wrong_parent"  # type: ignore[assignment]
            result.routed_to_silos.append(h3)
            result.wrong_parent_count += 1
            continue

    logger.info(
        "brief.h3_fit.complete",
        extra={
            "marginal": result.marginal_count,
            "wrong_parent": result.wrong_parent_count,
            "promoted": result.promoted_count,
            "reattached": len(result.reattached),
            "routed_to_silos": len(result.routed_to_silos),
        },
    )
    return result
