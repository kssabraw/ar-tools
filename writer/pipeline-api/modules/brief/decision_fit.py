"""Decision-fit directive (ported from the fanout brief generator's `decision_fit.py`,
adapted to this module's `claude_json` seam + the answer-contract detection shape).

When a query's best answer genuinely depends on the reader's situation, the brief
should carry a typed `decision_fit` directive the Writer renders as condition->option
guidance. The stages:

- **A1 detect** `decision_fit_qualifies` — gates on the answer-contract's
  `decision_fit_detection` (is_multi_answer + confidence>=tau + >=2 distinct conditions).
- **A3 source** `build_decision_fit_directive` — one Sonnet call producing >=2 distinct
  condition->option branches + an overarching default (drawn from the conditions +
  persona gaps / PAA / Reddit).
- **A4 gate** `detect_partner_factor` (pure) — "never standalone": emit only when a
  qualifying partner factor is present among the selected sections.
- **A5 emit** — the typed `DecisionFitDirective` attached to `format_directives` by the
  caller (anchored on the lead H2).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

from models.brief import DecisionFitBranch, DecisionFitDirective

from .llm import claude_json

logger = logging.getLogger(__name__)

DECISION_FIT_TAU = 0.7
PARTNER_FACTORS = ("comparative_depth", "edge_case_detail", "direct_definitions")

LLMJsonFn = Callable[..., Awaitable[Any]]


def _distinct_conditions(detection: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in (detection.get("conditions") or []):
        text = str(c).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def decision_fit_qualifies(detection: dict, *, tau: float = DECISION_FIT_TAU) -> bool:
    """A1: the detection must flag a genuine multi-answer query with confidence at or
    above `tau` and at least two distinct reader conditions."""
    if not isinstance(detection, dict) or not detection.get("is_multi_answer"):
        return False
    try:
        confidence = float(detection.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence >= tau and len(_distinct_conditions(detection)) >= 2


def detect_partner_factor(intent_type: str, heading_dicts: list[dict]) -> Optional[str]:
    """A4 co-occurrence check over the selected sections. Returns the partner factor
    present, or None (don't emit decision-fit standalone)."""
    texts = " ".join((h.get("text") or "").lower() for h in heading_dicts)
    if intent_type == "comparison" or " vs " in texts or "versus" in texts or "compared" in texts:
        return "comparative_depth"
    if any(h.get("source") == "authority_gap_sme" for h in heading_dicts):
        return "edge_case_detail"
    if intent_type in ("informational", "informational-commercial") or "what is" in texts or "definition" in texts:
        return "direct_definitions"
    return None


_SYSTEM = (
    "This query needs DIFFERENT recommendations depending on the reader's situation. "
    "Produce >=2 mutually-distinct branches, each a reader CONDITION and the recommended "
    "OPTION for it, plus one overarching default/priority statement that holds across "
    "branches. State the condition first.\n\n"
    "Return ONLY this JSON object:\n"
    "{\n"
    '  "branches": [{"condition": "...", "option": "...", '
    '"source": "persona_gap|paa|reddit|llm"}],\n'
    '  "default_statement": "..."\n'
    "}"
)


async def build_decision_fit_directive(
    detection: dict,
    *,
    anchor_h2_text: str,
    persona_gaps: list[str],
    paa: list[str],
    reddit: list[str],
    partner_factor: Optional[str],
    llm_json_fn: Optional[LLMJsonFn] = None,
) -> Optional[DecisionFitDirective]:
    """A3 + A5. Returns the typed directive, or None when there's no partner factor
    (A4) or fewer than 2 distinct branches can be sourced. Enrichment — degrades to
    None on any LLM failure."""
    if partner_factor is None:
        return None
    conditions = _distinct_conditions(detection)
    context = (
        "Candidate reader conditions:\n" + "\n".join(f"- {c}" for c in conditions)
        + "\n\nPersona gap questions:\n" + "\n".join(f"- {q}" for q in (persona_gaps or [])[:8])
        + "\n\nPAA:\n" + "\n".join(f"- {q}" for q in (paa or [])[:8])
        + "\n\nReddit threads:\n" + "\n".join(f"- {t}" for t in (reddit or [])[:5])
    )
    call = llm_json_fn or claude_json
    try:
        out = await call(_SYSTEM, context, max_tokens=1024, temperature=0.3)
    except Exception as exc:  # noqa: BLE001 — enrichment; no directive on failure
        logger.warning("brief.decision_fit_failed", extra={"reason": repr(exc)})
        return None

    if not isinstance(out, dict):
        return None

    branches: list[DecisionFitBranch] = []
    seen: set[str] = set()
    for b in (out.get("branches") or []):
        if not isinstance(b, dict):
            continue
        condition = str(b.get("condition") or "").strip()
        option = str(b.get("option") or "").strip()
        if not condition or not option:
            continue
        key = condition.lower()
        if key in seen:
            continue
        seen.add(key)
        source = b.get("source") if b.get("source") in ("persona_gap", "paa", "reddit", "llm") else "llm"
        branches.append(DecisionFitBranch(condition=condition, option=option, source=source))

    if len(branches) < 2:
        return None

    return DecisionFitDirective(
        anchor_h2_text=anchor_h2_text,
        branches=branches,
        default_statement=str(out.get("default_statement") or "").strip(),
        partner_factor=partner_factor or "",
    )
