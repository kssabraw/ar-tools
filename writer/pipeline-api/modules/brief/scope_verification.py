"""Step 8.5 - Scope Verification (Brief Generator v2.0).

Implements PRD §5 Step 8.5. Single Claude Sonnet 4.6 LLM call that
catches the small percentage of H2s that pass all numerical constraints
but answer a different reader question than the title's promise.

This is the "TikTok Shop algorithm signals" failure mode from PRD §1 -
a heading topically related to TikTok Shop but answering "how do I
optimize" instead of "what is it".

Inputs (PRD §5 Step 8.5):
  - title (Step 3.5)
  - scope_statement (Step 3.5, includes the explicit "does not cover" clause)
  - All H2s selected by Step 8 (the MMR survivors)

Output (strict JSON, additionalProperties: false):
  {
    "verified_h2s": [
      {
        "h2_text": str,
        "scope_classification": "in_scope" | "borderline" | "out_of_scope",
        "reasoning": str (≤200 chars)
      }
    ]
  }

Routing (PRD §5 Step 8.5):
  in_scope     → keep H2; scope_classification stamped on candidate
  borderline   → keep H2; scope_classification stamped + metadata flag
  out_of_scope → REMOVE from selected; route to silo with
                 routed_from="scope_verification"; discard_reason set

Failure handling (PRD §5 Step 8.5):
  - Malformed JSON → retry with stricter prompt
  - On second failure → ACCEPT ALL H2s as in_scope and log a warning.
    Do not abort the run - selection has already produced a valid
    outline by mathematical constraints.
  - LLM classifies an H2 not in the input list → discard the rogue
    classification, log warning. (Guards against the LLM hallucinating
    headings that weren't there.)

Do NOT re-run Step 8 to fill the gap after out_of_scope removals.
PRD §5 Step 8.5 explicitly forbids this: re-running risks pulling in
candidates that would also fail scope verification, and the LLM call
is non-deterministic enough that a re-run loop is risky.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .graph import Candidate
from .llm import claude_json

logger = logging.getLogger(__name__)


MAX_REASONING_LEN = 200
VALID_CLASSIFICATIONS = frozenset({"in_scope", "borderline", "out_of_scope"})


@dataclass
class ScopeVerificationResult:
    """Output of scope verification (Step 8.5).

    Mutates each surviving Candidate in place: writes
    `scope_classification` ('in_scope' or 'borderline') on kept H2s and
    `discard_reason='scope_verification_out_of_scope'` on rejects.
    """

    kept: list[Candidate] = field(default_factory=list)
    rejected: list[Candidate] = field(default_factory=list)
    borderline_count: int = 0
    rejected_count: int = 0
    fallback_applied: bool = False  # True when both LLM attempts failed


LLMJsonFn = Callable[..., Awaitable[Any]]


SYSTEM_PROMPT = """\
You verify that each candidate H2 heading falls within the scope of the
article it would appear in.

Your role catches a specific failure mode: an H2 that is topically
related to the seed but answers a different reader question than the
title's promise. Example: a "what is TikTok Shop" article that includes
"How to optimize for the TikTok Shop algorithm" - topically related but
out of scope.

Process:
1. Read the title and scope_statement carefully. The scope_statement
   contains a "does not cover" clause naming what is explicitly out.
2. For each H2, decide whether an article delivering on the title would
   reasonably include this H2.
3. Use three classifications:
   - "in_scope": Reading the title, you'd expect this section.
   - "borderline": A reasonable reader could go either way; flag for
     human review but don't reject.
   - "out_of_scope": This belongs in a different article. Likely a
     spin-off topic worth its own piece.

Be conservative. Default to "in_scope" or "borderline". Only mark
"out_of_scope" when the heading clearly answers a different question
than the title commits to (e.g., the scope statement's "does not cover"
clause names the specific area).

Output strict JSON only - no preamble, no markdown fences, no commentary:
{
  "verified_h2s": [
    {
      "h2_text": "exact text of the H2 from the input",
      "scope_classification": "in_scope" | "borderline" | "out_of_scope",
      "reasoning": "≤200 chars: why this classification"
    }
  ]
}

You MUST classify every H2 in the input. The h2_text in your output
must match the input H2 text exactly so the routing logic can pair them.
"""


STRICTER_RETRY_SUFFIX = """\

CRITICAL: Your previous response was rejected for a validation failure.
Output ONLY the JSON object with the verified_h2s array. Each entry MUST
have h2_text matching the input exactly, scope_classification from
{in_scope, borderline, out_of_scope}, and a brief reasoning string.
"""


def _format_user_prompt(
    title: str,
    scope_statement: str,
    selected_h2s: list[Candidate],
) -> str:
    h2_lines = [f"  {i+1}. {c.text}" for i, c in enumerate(selected_h2s)]
    return (
        f"Article title: {title}\n\n"
        f"Scope statement:\n{scope_statement}\n\n"
        f"Selected H2 candidates ({len(selected_h2s)}):\n"
        + ("\n".join(h2_lines) if h2_lines else "(none)")
    )


def _validate_payload(
    payload: Any,
    selected_h2s: list[Candidate],
) -> tuple[bool, str, Optional[dict[str, tuple[str, str]]]]:
    """Validate LLM output against the strict schema.

    Returns (ok, reason, classifications_by_text). On success,
    classifications_by_text maps each H2 text to (classification,
    reasoning). LLM-classified texts that weren't in the input are
    silently dropped with a warning log; missing input texts default
    to in_scope at the caller level (separate from validation).
    """
    if not isinstance(payload, dict):
        return False, "payload_not_object", None

    verified = payload.get("verified_h2s")
    if not isinstance(verified, list):
        return False, "verified_h2s_not_list", None

    valid_texts = {c.text for c in selected_h2s}
    classifications: dict[str, tuple[str, str]] = {}
    rogue_count = 0

    for entry in verified:
        if not isinstance(entry, dict):
            continue
        h2_text = entry.get("h2_text")
        cls = entry.get("scope_classification")
        reason = entry.get("reasoning", "") or ""
        if not isinstance(h2_text, str) or not h2_text.strip():
            continue
        if cls not in VALID_CLASSIFICATIONS:
            continue
        if h2_text not in valid_texts:
            rogue_count += 1
            logger.warning(
                "brief.scope.rogue_classification",
                extra={"h2_text": h2_text, "classification": cls},
            )
            continue
        if not isinstance(reason, str):
            reason = ""
        classifications[h2_text] = (
            cls,
            reason.strip()[:MAX_REASONING_LEN],
        )

    # Even with rogue drops, if we got at least one valid classification
    # we accept the payload - the orchestrator will fill missing entries
    # with the default in_scope (PRD treats no-classification as a pass).
    if not classifications:
        return False, "no_valid_classifications", None

    return True, "ok", classifications


async def verify_scope(
    *,
    title: str,
    scope_statement: str,
    selected_h2s: list[Candidate],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> ScopeVerificationResult:
    """Run Step 8.5: classify each selected H2; route out-of-scope to silos.

    Mutates the input candidates in place:
      - in_scope / borderline → scope_classification stamped, kept
      - out_of_scope → discard_reason='scope_verification_out_of_scope'
        AND scope_classification stays None (so downstream silo routing
        recognizes them as scope-rejected, not borderline-kept)

    Failure handling: on double LLM failure, ACCEPT ALL H2s as in_scope
    and log a warning. Never aborts.

    Empty input → empty result, no LLM call.
    """
    if not selected_h2s:
        return ScopeVerificationResult()

    call = llm_json_fn or claude_json
    user = _format_user_prompt(title, scope_statement, selected_h2s)

    classifications: Optional[dict[str, tuple[str, str]]] = None
    last_error = "unknown"

    for attempt in (1, 2):
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
                "brief.scope.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        ok, reason, parsed = _validate_payload(payload, selected_h2s)
        if ok and parsed is not None:
            classifications = parsed
            logger.info(
                "brief.scope.verified",
                extra={
                    "attempt": attempt,
                    "classified_count": len(parsed),
                    "input_count": len(selected_h2s),
                },
            )
            break

        last_error = reason
        logger.warning(
            "brief.scope.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    fallback_applied = classifications is None
    if fallback_applied:
        # PRD: accept everything as in_scope, do NOT abort
        logger.warning(
            "brief.scope.fallback",
            extra={
                "reason": last_error,
                "fallback": "accept_all_as_in_scope",
                "h2_count": len(selected_h2s),
            },
        )
        classifications = {c.text: ("in_scope", "fallback_after_llm_failure")
                           for c in selected_h2s}

    kept: list[Candidate] = []
    rejected: list[Candidate] = []
    borderline = 0
    out_of_scope = 0

    for cand in selected_h2s:
        cls, _reason = classifications.get(cand.text, ("in_scope", "default_pass"))
        if cls == "out_of_scope":
            cand.discard_reason = "scope_verification_out_of_scope"
            # Leave scope_classification as None so the downstream silo
            # routing recognizes this as a rejection, not a kept-with-flag.
            cand.scope_classification = None
            rejected.append(cand)
            out_of_scope += 1
        else:
            cand.scope_classification = cls  # type: ignore[assignment]
            kept.append(cand)
            if cls == "borderline":
                borderline += 1

    logger.info(
        "brief.scope.complete",
        extra={
            "kept": len(kept),
            "rejected": out_of_scope,
            "borderline": borderline,
            "fallback_applied": fallback_applied,
        },
    )

    return ScopeVerificationResult(
        kept=kept,
        rejected=rejected,
        borderline_count=borderline,
        rejected_count=out_of_scope,
        fallback_applied=fallback_applied,
    )


# ----------------------------------------------------------------------
# Step 8.5b - Authority Gap H3 scope verification (PRD v2.0.3)
# ----------------------------------------------------------------------

H3_SYSTEM_PROMPT = """\
You verify that each candidate H3 sub-heading falls within the scope of
the article it would appear in.

These H3s come from the Universal Authority Agent (Step 9), which
generates content across three pillars: Human/Behavioral, Risk/Regulatory,
and Long-Term Systems. The agent sometimes drifts outside the article's
committed scope - for example, producing post-launch operational content
on a "how to set up X" article whose scope only covers signup-through-
first-listing. Your role catches that drift.

Process:
1. Read the title and scope_statement carefully. The scope_statement
   contains a "does not cover" clause naming what is explicitly out.
2. For each H3, decide whether an article delivering on the title would
   reasonably include this sub-heading.
3. Use three classifications:
   - "in_scope": Reading the title, you'd expect this H3 under one of
     the article's main sections.
   - "borderline": A reasonable reader could go either way; flag for
     human review but don't reject.
   - "out_of_scope": This belongs in a different article. Likely a
     spin-off topic worth its own piece.

Be conservative. Default to "in_scope" or "borderline". Only mark
"out_of_scope" when the H3 clearly answers a different question than
the title commits to, or when it touches an area named in the
"does not cover" clause.

Output strict JSON only - no preamble, no markdown fences:
{
  "verified_h3s": [
    {
      "h3_text": "exact text of the H3 from the input",
      "scope_classification": "in_scope" | "borderline" | "out_of_scope",
      "reasoning": "≤200 chars: why this classification"
    }
  ]
}

You MUST classify every H3 in the input. The h3_text in your output
must match the input exactly so the routing logic can pair them.
"""


@dataclass
class H3ScopeVerificationResult:
    """Output of Step 8.5b - Authority Gap H3 scope verification.

    Mutates each surviving Candidate in place: writes
    `scope_classification` ('in_scope' or 'borderline') on kept H3s and
    `discard_reason='scope_verification_out_of_scope'` on rejects.
    """

    kept: list[Candidate] = field(default_factory=list)
    rejected: list[Candidate] = field(default_factory=list)
    borderline_count: int = 0
    rejected_count: int = 0
    fallback_applied: bool = False


def _format_h3_user_prompt(
    title: str,
    scope_statement: str,
    h3s: list[Candidate],
) -> str:
    h3_lines = [f"  {i+1}. {c.text}" for i, c in enumerate(h3s)]
    return (
        f"Article title: {title}\n\n"
        f"Scope statement:\n{scope_statement}\n\n"
        f"Candidate Authority Gap H3s ({len(h3s)}):\n"
        + ("\n".join(h3_lines) if h3_lines else "(none)")
    )


def _validate_h3_payload(
    payload: Any,
    h3s: list[Candidate],
) -> tuple[bool, str, Optional[dict[str, tuple[str, str]]]]:
    """Validate Step 8.5b LLM output. Mirrors `_validate_payload` shape
    but reads `verified_h3s` / `h3_text` keys instead of `verified_h2s` /
    `h2_text`."""
    if not isinstance(payload, dict):
        return False, "payload_not_object", None
    verified = payload.get("verified_h3s")
    if not isinstance(verified, list):
        return False, "verified_h3s_not_list", None

    valid_texts = {c.text for c in h3s}
    classifications: dict[str, tuple[str, str]] = {}

    for entry in verified:
        if not isinstance(entry, dict):
            continue
        h3_text = entry.get("h3_text")
        cls = entry.get("scope_classification")
        reason = entry.get("reasoning", "") or ""
        if not isinstance(h3_text, str) or not h3_text.strip():
            continue
        if cls not in VALID_CLASSIFICATIONS:
            continue
        if h3_text not in valid_texts:
            logger.warning(
                "brief.scope_h3.rogue_classification",
                extra={"h3_text": h3_text, "classification": cls},
            )
            continue
        if not isinstance(reason, str):
            reason = ""
        classifications[h3_text] = (
            cls,
            reason.strip()[:MAX_REASONING_LEN],
        )

    if not classifications:
        return False, "no_valid_classifications", None

    return True, "ok", classifications


async def verify_h3_scope(
    *,
    title: str,
    scope_statement: str,
    h3s: list[Candidate],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> H3ScopeVerificationResult:
    """Step 8.5b - Authority Gap H3 scope verification (PRD v2.0.3).

    Runs after Step 9 emits Authority Gap H3s. Failure handling matches
    Step 8.5: on double LLM failure, accept all as `in_scope` (never
    aborts). Empty input short-circuits without an LLM call.

    Mutates the input candidates:
      - in_scope / borderline → scope_classification stamped, kept
      - out_of_scope → discard_reason='scope_verification_out_of_scope'
        AND scope_classification stays None (downstream silo routing
        recognizes scope-rejected H3s by the discard_reason).
    """
    if not h3s:
        return H3ScopeVerificationResult()

    call = llm_json_fn or claude_json
    user = _format_h3_user_prompt(title, scope_statement, h3s)

    classifications: Optional[dict[str, tuple[str, str]]] = None
    last_error = "unknown"

    for attempt in (1, 2):
        system = (
            H3_SYSTEM_PROMPT if attempt == 1
            else H3_SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX
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
                "brief.scope_h3.llm_failed",
                extra={"attempt": attempt, "error": str(exc)},
            )
            continue

        ok, reason, parsed = _validate_h3_payload(payload, h3s)
        if ok and parsed is not None:
            classifications = parsed
            logger.info(
                "brief.scope_h3.verified",
                extra={
                    "attempt": attempt,
                    "classified_count": len(parsed),
                    "input_count": len(h3s),
                },
            )
            break

        last_error = reason
        logger.warning(
            "brief.scope_h3.invalid",
            extra={"attempt": attempt, "reason": reason},
        )

    fallback_applied = classifications is None
    if fallback_applied:
        logger.warning(
            "brief.scope_h3.fallback",
            extra={
                "reason": last_error,
                "fallback": "accept_all_as_in_scope",
                "h3_count": len(h3s),
            },
        )
        classifications = {c.text: ("in_scope", "fallback_after_llm_failure")
                           for c in h3s}

    kept: list[Candidate] = []
    rejected: list[Candidate] = []
    borderline = 0
    out_of_scope = 0

    for cand in h3s:
        cls, _reason = classifications.get(cand.text, ("in_scope", "default_pass"))
        if cls == "out_of_scope":
            cand.discard_reason = "scope_verification_out_of_scope"
            cand.scope_classification = None
            rejected.append(cand)
            out_of_scope += 1
        else:
            cand.scope_classification = cls  # type: ignore[assignment]
            kept.append(cand)
            if cls == "borderline":
                borderline += 1

    logger.info(
        "brief.scope_h3.complete",
        extra={
            "kept": len(kept),
            "rejected": out_of_scope,
            "borderline": borderline,
            "fallback_applied": fallback_applied,
        },
    )

    return H3ScopeVerificationResult(
        kept=kept,
        rejected=rejected,
        borderline_count=borderline,
        rejected_count=out_of_scope,
        fallback_applied=fallback_applied,
    )
