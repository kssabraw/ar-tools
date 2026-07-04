"""Tool / API operation costs — the second grounding catalog for SerMaStr.

The Recipe Engine (services/recipe_engine.price_catalog) prices the agency's
*deliverable* tactics (links, content, reviews, GBP). This module prices the
*operational* actions a strategist proposal can call for — the paid third-party
tool/API runs the agency absorbs: geo-grid scans, DataForSEO SERP/backlink
pulls, keyword research, LABS visibility scans, page audits, etc.

Why a separate, human-maintained module: these are vendor per-run prices that
change and that only the team can source accurately. They're **researched on a
~6-month cadence** and updated here (a one-line PR — hand over the numbers and
they land). Until an entry is **verified**, the strategist shows "tool cost"
rather than a fabricated dollar — we never invent a number (that's the whole
reason the LLM stopped estimating costs).

To update after a research pass: fill `unit_cost`, flip `verified` to True, and
set `RESEARCHED_AT`. Everything downstream (the strategist grounding, the card,
the Doc export) then shows the real dollars automatically.

Pure — no I/O. `unit_cost` on an unverified row is a best-effort placeholder for
the team to confirm/replace, and is NOT used to display a dollar while
`verified` is False.
"""

from __future__ import annotations

# Set to the ISO date of the last real cost research pass when the numbers below
# are verified (kept None while every row is still an unverified placeholder).
RESEARCHED_AT: "str | None" = None

# task_type → {label, unit_cost (placeholder until verified), unit, verified, note}
# The `note` names the vendor/driver so the researcher knows exactly what to price.
TOOL_COSTS: dict[str, dict] = {
    "geo_grid_scan": {
        "label": "Maps geo-grid scan", "unit_cost": 0.0, "unit": "scan", "verified": False,
        "note": "Local Dominator — per full grid scan (grid size × keywords).",
    },
    "serp_snapshot": {
        "label": "Competitive SERP snapshot", "unit_cost": 0.0, "unit": "keyword", "verified": False,
        "note": "DataForSEO SERP (depth) + Backlinks enrichment on the top results, per keyword.",
    },
    "backlink_intel": {
        "label": "Offpage / referring-domain pull", "unit_cost": 0.0, "unit": "domain", "verified": False,
        "note": "DataForSEO Backlinks summary, per domain (client + each competitor).",
    },
    "competitor_gbp": {
        "label": "Competitor GBP profile fetch", "unit_cost": 0.0, "unit": "listing", "verified": False,
        "note": "Outscraper — per competitor GBP profile (+ review enrichment via DataForSEO).",
    },
    "keyword_research": {
        "label": "Keyword research run (Topic Fanout)", "unit_cost": 0.0, "unit": "run", "verified": False,
        "note": "OpenAI Responses + ScrapeOwl + TextRazor per fanout/cluster run.",
    },
    "keyword_market": {
        "label": "Keyword market data (CPC/volume)", "unit_cost": 0.0, "unit": "keyword", "verified": False,
        "note": "DataForSEO Keywords/Labs, per keyword (cached cross-client).",
    },
    "brand_scan": {
        "label": "AI-visibility scan (LABS)", "unit_cost": 0.0, "unit": "keyword-engine", "verified": False,
        "note": "Per keyword × engine cell across the 6 engines (OpenAI/Anthropic/Gemini/Perplexity/DataForSEO AIO).",
    },
    "page_audit": {
        "label": "On-page audit (nlp 8-engine)", "unit_cost": 0.0, "unit": "page", "verified": False,
        "note": "ScrapeOwl + TextRazor + Claude scoring, per page scored.",
    },
    "gsc_research": {
        "label": "GSC Research run", "unit_cost": 0.0, "unit": "run", "verified": False,
        "note": "GSC API (free) + DataForSEO market enrichment on the win candidates.",
    },
}


def tool_catalog() -> dict[str, dict]:
    """{task_type: {task_type, label, unit_cost, unit, assignee, verified, note}}
    for the tool/API operations. `unit_cost` is only meaningful (shown) when
    `verified` is True. Pure."""
    return {
        task_type: {
            "task_type": task_type,
            "label": spec["label"],
            "unit_cost": float(spec["unit_cost"]),
            "unit": spec["unit"],
            "assignee": None,          # operational — no roles-matrix owner
            "verified": bool(spec["verified"]),
            "note": spec["note"],
        }
        for task_type, spec in TOOL_COSTS.items()
    }


def unverified_operations() -> list[dict]:
    """The tool operations still awaiting a real price — the checklist for the
    next 6-month research pass. Pure."""
    return [
        {"task_type": t, "label": s["label"], "unit": s["unit"], "note": s["note"]}
        for t, s in TOOL_COSTS.items()
        if not s["verified"]
    ]
