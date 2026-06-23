"""Brief Generator — decision-fit directive (M13 slice 5c-iv, aio §3.1 / §3.3).

The A1 detector fires at Step 3 (intent.py -> `decision_fit_qualifies`). This module does
the rest of STAGE A at selection time:

- **A3 source** the branch material: condition -> option map + an overarching default,
  drawn from the A1 conditions + persona gaps / PAA / Reddit (one LLM call).
- **A4 gate** "never standalone": emit only if a qualifying partner factor
  (comparative_depth / edge_case_detail / direct_definitions) is present among the
  selected sections.
- **A5 emit** the typed `format_directive` (attached to the reserved anchor H2 by the
  caller). The Writer (M14) renders + validates it (STAGE B, deferred).

`detect_partner_factor` is pure; `build_decision_fit_directive` makes the A3 LLM call.
"""

from __future__ import annotations

PARTNER_FACTORS = ("comparative_depth", "edge_case_detail", "direct_definitions")


def detect_partner_factor(intent_type: str, heading_dicts: list[dict]) -> str | None:
    """A4 co-occurrence check over the selected sections. Returns the partner factor
    present, or None (don't emit decision-fit standalone). Commercial-page gating
    (multiple_languages) is deferred (aio §3.4)."""
    texts = " ".join((h.get("text") or "").lower() for h in heading_dicts)
    if intent_type == "comparison" or " vs " in texts or "versus" in texts or "compared" in texts:
        return "comparative_depth"
    if any(h.get("source") == "authority_gap_sme" for h in heading_dicts):
        return "edge_case_detail"
    if intent_type in ("informational", "informational-commercial") or "what is" in texts or "definition" in texts:
        return "direct_definitions"
    return None


def build_decision_fit_directive(
    detection: dict, *, anchor_h2_text: str, persona_gaps: list[dict], paa: list[str],
    reddit: list[dict], partner_factor: str | None, llm,
) -> dict | None:
    """A3 + A5. Returns the typed `format_directive` (with `anchor_h2_text` for the caller
    to resolve `section_id`), or None when there's no partner factor (A4) or fewer than 2
    distinct branches can be sourced."""
    if partner_factor is None:
        return None
    conditions = [
        c.get("condition") for c in (detection.get("candidate_conditions") or [])
        if isinstance(c, dict) and (c.get("condition") or "").strip()
    ]
    schema = {
        "type": "object",
        "properties": {
            "branches": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "option": {"type": "string"},
                    "source": {"type": "string", "enum": ["persona_gap", "paa", "reddit", "llm"]},
                },
                "required": ["condition", "option"],
            }},
            "default_statement": {"type": "string"},
        },
        "required": ["branches", "default_statement"],
    }
    context = (
        "Candidate reader conditions:\n" + "\n".join(f"- {c}" for c in conditions)
        + "\n\nPersona gap questions:\n" + "\n".join(f"- {g.get('question', '')}" for g in persona_gaps[:8])
        + "\n\nPAA:\n" + "\n".join(f"- {q}" for q in paa[:8])
        + "\n\nReddit threads:\n" + "\n".join(f"- {(d.get('title') or '')}" for d in reddit[:5])
    )
    try:
        out = llm.call_tool(
            system=(
                "This query needs DIFFERENT recommendations depending on the reader's "
                "situation. Produce >=2 mutually-distinct branches, each a reader CONDITION "
                "and the recommended OPTION for it, plus one overarching default/priority "
                "statement that holds across branches. State the condition first."
            ),
            user=context,
            tool_name="decision_fit_branches",
            tool_description="Return condition->option branches and a default statement.",
            input_schema=schema,
            purpose="brief_decision_fit",
        )
    except Exception:  # noqa: BLE001 — enrichment; no directive on failure
        return None
    branches = [
        {"condition": (b.get("condition") or "").strip(), "option": (b.get("option") or "").strip(),
         "source": b.get("source", "llm")}
        for b in (out.get("branches") or [])
        if isinstance(b, dict) and (b.get("condition") or "").strip() and (b.get("option") or "").strip()
    ]
    if len({b["condition"].lower() for b in branches}) < 2:
        return None
    return {
        "type": "decision_fit",
        "anchor_h2_text": anchor_h2_text,          # caller resolves section_id from this
        "branches": branches,
        "default_statement": (out.get("default_statement") or "").strip(),
        "partner_factor": partner_factor,
        "constraints": {"condition_first": True, "min_branches": 2, "distinct_branches": True},
        "detector": {"confidence": detection.get("confidence"), "rationale": detection.get("rationale", "")},
    }
