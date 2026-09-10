"""Website Builder — assembling a Warranty / Guarantee page.

The warranty page (reference §5.1, Warranty / Guarantee — ⭐ SOP extension,
Writer #12) is risk reversal: workmanship guarantees, warranty terms, coverage.
Its required input is "actual warranty terms (legal sign-off)" and its pitfall is
"vague guarantee language that overpromises" — so the coverage terms, the claim
steps and the FAQ answers are facts the operator enters, and this module INVENTS
NONE of them:

* the coverage table, the claim StepList and the FAQ pass straight through to
  `sections` frontmatter, which the /warranty/ route renders deterministically;
* only the connective PROSE — the promise lede and the manufacturer-vs-workmanship
  explainer — is optionally narrated by one LLM call, whose sole job is to turn
  the operator's notes into plain, confident language (reference angle: "the
  promise in plain language … put conditions after the promise"). It is
  invent-nothing and best-effort: a disabled/failed narration falls back to the
  operator's raw text, and the narration NEVER touches a coverage term, duration,
  claim step or FAQ answer.

The warranty singleton is one per site at /warranty/, id-addressed like the FAQ.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from services import report_llm

logger = logging.getLogger(__name__)

_EXPLAINER_HEADING = "Manufacturer vs. workmanship"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _coverage_rows(warranty: dict) -> list[dict]:
    """Coverage SpecTable rows: {item, detail, duration}. A row with no item drops."""
    out: list[dict] = []
    for raw in warranty.get("coverage") or []:
        if not isinstance(raw, dict):
            continue
        item = _clean(raw.get("item"))
        if not item:
            continue
        out.append(
            {
                "item": item,
                "detail": _clean(raw.get("detail")),
                "duration": _clean(raw.get("duration")),
            }
        )
    return out


def _claim_steps(warranty: dict) -> list[str]:
    """Ordered claim-process steps — non-empty strings, order preserved."""
    return [s for s in (_clean(x) for x in (warranty.get("claim_steps") or [])) if s]


def _faq_items(warranty: dict) -> list[dict]:
    """FAQ pairs: {q, a}, both sides non-empty (feeds FAQAccordion + FAQPage schema)."""
    out: list[dict] = []
    for raw in warranty.get("faq") or []:
        if not isinstance(raw, dict):
            continue
        q, a = _clean(raw.get("q")), _clean(raw.get("a"))
        if q and a:
            out.append({"q": q, "a": a})
    return out


def _meta_description(promise: str, warranty: dict) -> str:
    """A meta description from the promise (the hook), trimmed."""
    text = " ".join((promise or _clean(warranty.get("headline"))).split())
    if len(text) <= 160:
        return text
    return text[:160].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def build_warranty_content(warranty: dict, narrated: Optional[dict] = None) -> dict:
    """The `content` dict a website_pages row stores for the warranty singleton.

    Pure — mirrors the core-pages/project shape. The promise and the explainer are
    whatever was narrated where the LLM produced it, else the operator's raw text.
    The body carries only the manufacturer-vs-workmanship explainer (rendered via
    `<Content />`); the promise, coverage table, claim steps and FAQ ride in
    `sections`, which the /warranty/ route renders deterministically.
    """
    warranty = warranty or {}
    narrated = narrated or {}

    promise = _clean(narrated.get("promise")) or _clean(warranty.get("promise"))
    explainer = _clean(narrated.get("explainer")) or _clean(
        warranty.get("manufacturer_vs_workmanship")
    )

    sections: dict[str, Any] = {}
    if promise:
        sections["promise"] = promise
    coverage = _coverage_rows(warranty)
    if coverage:
        sections["coverage"] = coverage
    steps = _claim_steps(warranty)
    if steps:
        sections["claimSteps"] = steps
    faq = _faq_items(warranty)
    if faq:
        sections["faqItems"] = faq

    body = f"## {_EXPLAINER_HEADING}\n\n{explainer}" if explainer else ""

    return {
        "title": _clean(warranty.get("headline")) or "Our Guarantee",
        "description": _meta_description(promise, warranty),
        "body": body,
        "frontmatter": {"sections": sections},
    }


# --------------------------------------------------------------------------
# Narration — one invent-nothing LLM call, best-effort
# --------------------------------------------------------------------------

_NARRATE_SYSTEM = (
    "You write the connective copy for a home-service business's warranty / "
    "guarantee page. You are given the operator's own notes for two things — the "
    "PROMISE (what the business guarantees) and an EXPLAINER (manufacturer vs. "
    "workmanship coverage) — plus the coverage terms. You return the same two, "
    "rewritten as clear, confident, plain-language prose.\n\n"
    "HARD RULES:\n"
    "1. Invent NOTHING. A warranty page has legal weight. Use only facts present "
    "in the notes and coverage terms: never add, extend, shorten or invent a "
    "duration, a covered item, a condition, or a claim requirement. Keep every "
    "specific term exactly as given.\n"
    "2. Never overpromise. Do not add absolutes ('lifetime', 'no questions "
    "asked', 'everything covered') that are not already in the notes — vague "
    "guarantee language that overpromises is the one thing this page must avoid.\n"
    "3. Lead with the promise, then the conditions — state what IS guaranteed "
    "plainly and up front; qualifications come after. Match the client's brand "
    "voice where one is provided. If a section's notes are empty, return an empty "
    "string for it."
)

_NARRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "promise": {
            "type": "string",
            "description": "The guarantee in plain language, promise first, as prose.",
        },
        "explainer": {
            "type": "string",
            "description": "Manufacturer vs. workmanship coverage explained plainly, as prose.",
        },
    },
    "required": ["promise", "explainer"],
    "additionalProperties": False,
}


def _narrate_user(warranty: dict, brand_text: str) -> str:
    lines = [f"BUSINESS GUARANTEE: {_clean(warranty.get('headline')) or 'a workmanship guarantee'}"]
    coverage = _coverage_rows(warranty)
    if coverage:
        lines.append(
            "COVERAGE TERMS (facts — do not change): "
            + "; ".join(
                " ".join(p for p in (c["item"], c["detail"], f"({c['duration']})" if c["duration"] else "") if p)
                for c in coverage
            )
        )
    lines.append(f"\nPROMISE — operator notes:\n{_clean(warranty.get('promise')) or '(none given)'}")
    lines.append(
        f"\nMANUFACTURER VS. WORKMANSHIP — operator notes:\n"
        f"{_clean(warranty.get('manufacturer_vs_workmanship')) or '(none given)'}"
    )
    prompt = "\n".join(lines)
    if (brand_text or "").strip():
        prompt += "\n\nBRAND VOICE (match it):\n" + brand_text.strip()
    prompt += (
        "\n\nRewrite the promise and the explainer as plain-language prose, using "
        "only the facts above. If a section's notes say '(none given)', return an "
        "empty string for it."
    )
    return prompt


async def narrate_warranty(warranty: dict, client: Optional[dict]) -> Optional[dict]:
    """Turn the operator's promise + explainer notes into prose. Best-effort:
    returns `{promise, explainer}` or None on any failure, so the caller falls
    back to the raw supplied text.

    Skips the call entirely when there is no prose to narrate (a coverage-table-
    only warranty) so a bare warranty page costs nothing.
    """
    warranty = warranty or {}
    if not (_clean(warranty.get("promise")) or _clean(warranty.get("manufacturer_vs_workmanship"))):
        return None
    try:
        from services.voice_card_service import source_texts

        brand_text, _icp = source_texts(client or {})
        out = await report_llm.run_forced_tool(
            provider="anthropic",
            model=settings.website_core_pages_model,
            system=_NARRATE_SYSTEM,
            user=_narrate_user(warranty, brand_text),
            tool_name="write_warranty_copy",
            tool_description="Return the narrated promise and manufacturer-vs-workmanship explainer.",
            input_schema=_NARRATE_SCHEMA,
            max_tokens=settings.website_core_pages_max_tokens,
            log_tag="website_warranty",
        )
    except Exception as exc:  # noqa: BLE001 — narration is an enhancement, never a gate
        logger.warning("website_warranty.narrate_failed", extra={"error": str(exc)})
        return None
    if not isinstance(out, dict):
        return None
    return {"promise": _clean(out.get("promise")), "explainer": _clean(out.get("explainer"))}
