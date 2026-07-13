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
        "city": {
            "type": "string",
            "description": "The US city named in the search, if any (e.g. "
                           "'Cleveland'). Empty string if no city is mentioned.",
        },
        "state": {
            "type": "string",
            "description": "The US state named in the search as its 2-letter "
                           "USPS code (e.g. 'OH' for Ohio). Empty string if no "
                           "state is mentioned.",
        },
        "county": {
            "type": "string",
            "description": "The US county named in the search, WITHOUT the word "
                           "'County'/'Parish' (e.g. 'Cuyahoga'). Empty string if "
                           "no county is mentioned.",
        },
    },
    "required": ["category", "confidence"],
}

# USPS state codes (50 + DC) + full-name fallback, for normalizing the model's
# `state` extraction to a 2-letter code the board filter expects.
_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
}
_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "washington dc": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def normalize_state(raw: Any) -> str | None:
    """Model's `state` extraction → a valid 2-letter USPS code, or None. Accepts
    a code ('oh', 'OH') or a full name ('Ohio'); anything unrecognized → None so
    a bad guess never over-filters the board. Pure."""
    s = str(raw or "").strip()
    if not s:
        return None
    up = s.upper()
    if up in _STATE_CODES:
        return up
    return _STATE_NAME_TO_CODE.get(s.lower())


def resolve_location(result: dict[str, Any] | None) -> dict[str, Any]:
    """Extract {city, state, county} from the model result. State is normalized
    to a 2-letter code (else None); city/county are trimmed strings (else None).
    Pure — location applies INDEPENDENTLY of the category match/threshold, so a
    pure-location query ('Cuyahoga County Ohio') still filters even when no
    service category is present."""
    r = result or {}

    def _clean(key: str) -> str | None:
        v = str(r.get(key) or "").strip()
        # strip a trailing "County"/"Parish" if the model included it anyway
        if key == "county" and v:
            for suf in (" county", " parish", " borough"):
                if v.lower().endswith(suf):
                    v = v[: -len(suf)].strip()
        return v or None

    return {"city": _clean("city"), "state": normalize_state(r.get("state")),
            "county": _clean("county")}


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
        "You parse a user's free-text market search into a business category "
        "and/or a US location. TWO independent jobs:\n"
        "1) CATEGORY: map any home-services business type to exactly ONE "
        "category from the fixed list, copied verbatim, plus confidence (0-1). "
        'If no listed category clearly applies, return category "NONE". Be '
        "conservative: confidence >= 0.85 only when genuinely sure. Never "
        "invent a category not in the list.\n"
        "2) LOCATION: extract any US city, state (as a 2-letter USPS code), and "
        "county (without the word 'County') mentioned. Leave a location field "
        "empty if not present.\n"
        "A query may have a category only ('roofers'), a location only "
        "('Cuyahoga County Ohio'), or both ('plumbers in Dallas TX')."
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
            tool_description="Report the best-matching category + confidence, "
                             "and any US city/state/county in the search.",
            input_schema=_TOOL_SCHEMA,
            max_tokens=200,
            log_tag="leadoff_category_match",
        )
    except Exception:  # noqa: BLE001 — best-effort: never 500 the search box
        logger.warning("leadoff_category_match.llm_failed", exc_info=True)
        return _no_data(error="match_failed")
    # Category (thresholded) and location (independent) are merged — a query can
    # carry either, both, or neither.
    out = resolve_llm_result(result, categories,
                             settings.leadoff_category_match_threshold)
    out.update(resolve_location(result))
    return out
