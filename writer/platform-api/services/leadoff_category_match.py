"""LeadOff category smart-search — map a free-text search to a scanned board
category via one forced Claude (Sonnet) tool call, gated by a confidence
threshold.

The user types a loose description of a business type ("someone to fix my
roof", "tree guys", "ac repair") and the model picks the single best category
from the scanned set + a 0-1 confidence. Below
`leadoff_category_match_threshold` (0.85) — or when the model can't map the
text to a real listed category — the result is **"No Data Provided"**: the UI
declines to guess rather than filtering the board on a shaky match. The
candidate set is the scanned categories (`leadoff.list_categories`), so a
positive match always points at a category the board actually has.

The threshold + validation live in the pure `resolve_llm_result` (unit-tested);
the LLM call is best-effort and never raises (a provider failure returns
"No Data Provided", not a 500).
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

NO_DATA = "No Data Provided"

_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "The single best-matching category, copied VERBATIM "
                           "from the provided list — or the exact string NONE "
                           "if no listed category is a plausible match.",
        },
        "confidence": {
            "type": "number",
            "description": "Confidence from 0.0 to 1.0 that this category is "
                           "what the user's search refers to.",
        },
    },
    "required": ["category", "confidence"],
}


def _no_data(confidence: float = 0.0, **extra: Any) -> dict[str, Any]:
    return {"matched": False, "category": None, "label": NO_DATA,
            "confidence": round(max(0.0, min(1.0, confidence)), 3), **extra}


def resolve_llm_result(result: dict[str, Any] | None, categories: list[str],
                       threshold: float) -> dict[str, Any]:
    """Turn the model's ``{category, confidence}`` into the API result. Pure.

    Returns "No Data Provided" (matched=False) when the model returned NONE, a
    category not in the candidate list, or confidence below `threshold`. A
    valid, confident match returns the canonical category string (matched on a
    case-insensitive basis so casing drift never sinks a real match)."""
    index = {c.strip().lower(): c for c in categories if c and c.strip()}
    raw_cat = str((result or {}).get("category") or "").strip()
    try:
        conf = float((result or {}).get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    canonical = index.get(raw_cat.lower())
    if canonical is None or raw_cat.lower() == "none" or conf < threshold:
        return _no_data(conf)
    return {"matched": True, "category": canonical, "label": canonical,
            "confidence": round(conf, 3)}


async def match_category(query: str, categories: list[str]) -> dict[str, Any]:
    """One forced Sonnet tool call mapping `query` → a scanned category +
    confidence, then thresholded by :func:`resolve_llm_result`. Best-effort:
    an empty query, no categories, or any LLM failure returns "No Data
    Provided" rather than raising."""
    q = (query or "").strip()
    if not q or not categories:
        return _no_data()
    from services import report_llm

    system = (
        "You map a user's free-text description of a home-services business "
        "type to exactly ONE category from a fixed list. Return the category "
        "string copied verbatim from the list, plus your confidence (0-1). "
        "If the text does not clearly correspond to any listed category, return "
        'category "NONE". Be conservative: only give confidence >= 0.85 when you '
        "are genuinely sure the user means that specific category. Never invent "
        "a category that is not in the list."
    )
    user = (
        f"User search: {q!r}\n\n"
        "Categories (choose exactly one, copied verbatim, or NONE):\n"
        + "\n".join(f"- {c}" for c in categories)
    )
    try:
        result = await report_llm.run_forced_tool(
            provider="anthropic",
            model=settings.leadoff_category_match_model,
            system=system,
            user=user,
            tool_name="report_match",
            tool_description="Report the best-matching category and your confidence.",
            input_schema=_TOOL_SCHEMA,
            max_tokens=200,
            log_tag="leadoff_category_match",
        )
    except Exception:  # noqa: BLE001 — best-effort: never 500 the search box
        logger.warning("leadoff_category_match.llm_failed", exc_info=True)
        return _no_data(error="match_failed")
    return resolve_llm_result(result, categories,
                              settings.leadoff_category_match_threshold)
