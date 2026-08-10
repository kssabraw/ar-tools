"""Loss-framed LLM phrasing pass for the per-prospect "Why call?" hook.

`outreach_justification.build_justification` assembles the deterministic, fact-grounded talking
points and a spoken hook. That hook is honest but templated, so two prospects in one submarket read
alike. This module rewrites it into a **compelling, loss-framed, per-prospect** opener — the module
docstring's anticipated "LLM phrasing pass layered ON TOP, grounded on the facts this module already
assembles." It reuses `report_llm.run_forced_tool_sync`, the same grounded forced-tool transport the
maps + rank-analysis narratives use.

**The governing invariant does not relax for fear-of-loss copy — it gets teeth.** Loss framing is
exactly where an LLM drifts into a fabricated "you're losing $8k/month" (unprovable AND falsifiable
in one sentence, which the module says costs the call — PRD §9a.2). So:

  * the prompt forbids inventing money / revenue / lead-volume / competitor names, and
  * `guard_output` (pure, deterministic) REJECTS any output that slips a currency figure, a
    per-month/ROI number, or an estimated lead/job/sale/customer count through — on rejection the
    caller keeps the deterministic loss-framed hook. A regex cannot be talked out of a verdict.

Everything is best-effort: no API key, a failed call, a malformed response, or a guard rejection all
return None, and the deterministic hook stands. A report must never fail to render because phrasing
was unavailable. The result is cached per (prospect, snapshot) upstream, so determinism/replayability
lives at the cache (identical re-reads) rather than the model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

TOOL_NAME = "emit_call_hook"

# The forced tool: the model returns a rewritten hook and (optionally) rephrased talking points. It
# never returns facts, numbers-as-data, or an element it wasn't given — the caller keeps the
# deterministic `facts`/`element`, so this can only ever RE-WORD, never re-ground.
EMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hook": {
            "type": "string",
            "description": "The spoken opener a caller reads before dialing: 1-2 sentences, second "
            "person, loss-framed. Uses ONLY the provided facts.",
        },
        "talking_points": {
            "type": "array",
            "description": "Each provided talking point, rewritten as one loss-framed sentence. Keep "
            "each point's `element` exactly as given; rewrite only its text.",
            "items": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["element", "text"],
            },
        },
    },
    "required": ["hook"],
}

_SYSTEM = (
    "You write the single opening line a salesperson says on a cold call to a LOCAL BUSINESS OWNER. "
    "Your goal is to make the owner feel what they are losing RIGHT NOW — customers, calls and "
    "clicks going to named competitors while they're invisible on Google. Loss, not opportunity: "
    "frame it as happening today, in the present continuous.\n\n"
    "HARD RULES (breaking one is worse than a dull line — it loses the call):\n"
    "1. Use ONLY the facts provided. Every number, percentage and competitor name must appear in "
    "the facts. If a fact isn't given, you don't have it — don't imply it.\n"
    "2. NEVER invent or estimate money: no dollars, revenue, ROI, or a number of leads / jobs / "
    "sales / customers per month. You have NO such data. Do not hint at one.\n"
    "3. NEVER name a business the facts don't name. NEVER cite a number the facts don't contain.\n"
    "4. NO promises about results ('we'll get you ranked #1'). Diagnose the loss; don't promise a fix.\n"
    "5. Second person ('you'), plain and direct. The hook is 1-2 sentences.\n\n"
    "Then rewrite each talking point into one loss-framed sentence using only its own facts, keeping "
    "its `element` unchanged. Return everything through the emit_call_hook tool."
)


def _fact_lines(justification: dict[str, Any]) -> str:
    lines: list[str] = []
    for p in justification.get("talking_points") or []:
        el = p.get("element")
        text = p.get("text")
        facts = p.get("facts") or {}
        lines.append(f"- [{el}] {text}\n    facts: {json.dumps(facts, default=str, sort_keys=True)}")
    return "\n".join(lines)


def build_prompt(justification: dict[str, Any]) -> tuple[str, str]:
    """(system, user) for the phrasing call. Pure. The user message carries the business identity,
    the search, which element is the strongest lead, the deterministic hook as the baseline to
    sharpen, and every talking point with its raw facts — so the model has exactly the grounded
    material and nothing else."""
    name = justification.get("prospect_name") or "This business"
    keyword = justification.get("provenance", {}).get("keyword") or ""
    submarket = justification.get("provenance", {}).get("submarket") or ""
    user = (
        f"Business: {name}\n"
        f'Search: "{keyword}" in {submarket}\n'
        f"Strongest lead angle (open with this): {justification.get('hook_element')}\n\n"
        f"Current draft opener (make it sharper and more loss-focused, same facts):\n"
        f"  {justification.get('hook')}\n\n"
        f"Measured facts you may use (nothing else exists):\n{_fact_lines(justification)}"
    )
    return _SYSTEM, user


# --- the grounding guard (the invariant's teeth) ----------------------------------------------

# Fabrication patterns that fear-of-loss copy tends to invent. The facts never attach a number to
# money or to a per-period volume of leads/jobs/sales/customers/clicks — those measurements don't
# exist — so any of these in the output means the model made a number up. Percentages, review
# counts, "top 3", miles and point counts are all legitimate (they come from the facts) and are
# deliberately NOT matched here.
_FORBIDDEN = [
    re.compile(r"[$£€]"),                                   # any currency symbol
    re.compile(r"\brevenue\b", re.I),
    re.compile(r"\bdollars?\b", re.I),
    re.compile(r"\b(per|a)\s+month\b", re.I),               # "$X per month" / "a month"
    re.compile(r"/mo\b", re.I),
    re.compile(r"\bmonthly\b", re.I),
    re.compile(r"\b(hundreds|thousands|dozens)\s+of\b", re.I),
    re.compile(r"\b\d[\d,]*\s*k\b", re.I),                  # 5k, 10k
    # a number glued to a business-outcome noun ("50 leads", "12 new customers a week")
    re.compile(
        r"\b\d[\d,]*\s+(?:new\s+|potential\s+)?"
        r"(leads?|jobs?|sales?|calls?|customers?|clients?|clicks?|visitors?|conversions?)\b",
        re.I,
    ),
]


def has_fabricated_number(text: str) -> bool:
    """True if `text` asserts a money figure or an estimated business-outcome volume — the fabricated
    numbers loss-framing invites, none of which the facts contain. Pure."""
    return any(p.search(text or "") for p in _FORBIDDEN)


def guard_output(hook: str, talking_points: list[dict[str, Any]]) -> bool:
    """True if the LLM output is safe to ship — no fabricated money / volume number anywhere in the
    hook or the rewritten points. Pure and deterministic; a rejection sends the caller back to the
    deterministic hook. Known limit: this targets the money/volume fabrication mode specifically (the
    real risk fear-of-loss framing introduces); an invented competitor NAME is guarded by the prompt
    + by the caller keeping each point's original `element`/`facts`, not re-detected here."""
    if has_fabricated_number(hook):
        return False
    for p in talking_points or []:
        if isinstance(p, dict) and has_fabricated_number(str(p.get("text") or "")):
            return False
    return True


# --- fingerprint (cache key over the grounded facts) ------------------------------------------


def facts_fingerprint(justification: dict[str, Any]) -> str:
    """A stable SHA-256 over the facts that feed phrasing: the deterministic hook + each talking
    point's element + facts (NOT its prose, which is what we're regenerating). Same measured facts →
    same fingerprint → the cache returns the stored hook and the LLM is not called again; a new scan
    changes a number → new fingerprint → regenerate. Pure."""
    payload = {
        "hook": justification.get("hook"),
        "hook_element": justification.get("hook_element"),
        "points": [
            {"element": p.get("element"), "facts": p.get("facts")}
            for p in (justification.get("talking_points") or [])
        ],
    }
    blob = json.dumps(payload, default=str, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- the impure generate step -----------------------------------------------------------------


def _resolve_model(provider: str) -> str:
    from config import settings

    if provider == "openai":
        return settings.outreach_call_hook_openai_model
    return settings.outreach_call_hook_model


def generate_hook(justification: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Rewrite the hook (and rephrase the talking points) into loss-framed prose grounded on the
    justification's facts, or None on any failure. Best-effort: gated on the enable flag + a measured
    justification, wrapped so no provider error, malformed response, or guard rejection can break the
    report — the deterministic hook stands in every None case."""
    from config import settings
    from services import report_llm

    if not settings.outreach_call_hook_llm_enabled:
        return None
    if not justification.get("measured"):
        return None

    system, user = build_prompt(justification)
    provider = settings.outreach_call_hook_provider
    try:
        out = report_llm.run_forced_tool_sync(
            provider=provider,
            model=_resolve_model(provider),
            system=system,
            user=user,
            tool_name=TOOL_NAME,
            tool_description="Return a loss-framed, fact-grounded call hook and rephrased talking points.",
            input_schema=EMIT_SCHEMA,
            max_tokens=settings.outreach_call_hook_max_tokens,
            log_tag="outreach_call_hook",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; the deterministic hook is the fallback
        logger.warning("outreach_call_hook_llm_failed", extra={"error": str(exc)[:200]})
        return None

    hook = (out or {}).get("hook")
    if not isinstance(hook, str) or not hook.strip():
        return None
    points = [p for p in (out.get("talking_points") or []) if isinstance(p, dict) and p.get("text")]
    if not guard_output(hook, points):
        logger.warning("outreach_call_hook_guard_rejected", extra={"hook": hook[:200]})
        return None
    return {"hook": hook.strip(), "talking_points": points}
