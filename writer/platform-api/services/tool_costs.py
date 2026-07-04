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

# ISO date of the last real cost research pass. Prices below were researched on
# this date from public vendor pricing × the suite's actual per-op call counts.
RESEARCHED_AT: "str | None" = "2026-07-04"

# task_type → {label, unit_cost, unit, verified, note}
# `verified` True → the strategist shows the real dollar. False → still shows
# "tool cost" (a researched estimate is kept in unit_cost as a starting point,
# but isn't displayed until confirmed). The `note` documents the derivation +
# confidence so the next research pass can confirm/refine each line.
#
# LLM model rates used for the token-driven ops (researched 2026-07-04, confirmed
# with the team): GPT-5.4 $2.50/$15 (mini $0.75/$4.50); Claude Sonnet $3/$15;
# Claude Opus 4.8 $5/$25; Gemini 2.5 Flash $0.30/$2.50; Perplexity Sonar $1/$1
# + ~$5–12/1k requests. The on-page audit scores with Sonnet.
TOOL_COSTS: dict[str, dict] = {
    "geo_grid_scan": {
        "label": "Maps geo-grid scan", "unit_cost": 0.37, "unit": "keyword (5-mi grid)", "verified": True,
        "note": "Local Dominator: 1 credit = 1 keyword×coordinate; $197/mo ÷ 65,000 credits = "
                "$0.00303/credit. 5-mi grid = 121 pins → ~$0.37/keyword (3-mi ≈ $0.15, 7-mi ≈ $0.68).",
    },
    "serp_snapshot": {
        "label": "Competitive SERP snapshot", "unit_cost": 0.50, "unit": "keyword", "verified": True,
        "note": "DataForSEO SERP Live Advanced (~$0.004) + ~10 Backlinks summaries on the top results "
                "+ ~10 domain-DR pulls (~$0.02–0.05 each) ≈ $0.50/keyword.",
    },
    "backlink_intel": {
        "label": "Offpage / referring-domain pull", "unit_cost": 0.03, "unit": "domain", "verified": True,
        "note": "DataForSEO Backlinks summary: $0.02/request + $0.00003/row ≈ $0.03 per domain "
                "(client + each competitor).",
    },
    "competitor_gbp": {
        "label": "Competitor GBP profile fetch", "unit_cost": 0.30, "unit": "listing", "verified": True,
        "note": "Outscraper place ($3/1k = $0.003) + ~100 reviews ($3/1k = $0.30) + DataForSEO business "
                "($0.0015) ≈ $0.30/listing (reviews dominate).",
    },
    "keyword_market": {
        "label": "Keyword market data (CPC/volume)", "unit_cost": 0.001, "unit": "keyword", "verified": True,
        "note": "DataForSEO Labs: $0.01/task + $0.0001/result, batched + cached cross-client ≈ "
                "$0.001/keyword marginal.",
    },
    "gsc_research": {
        "label": "GSC Research run", "unit_cost": 0.05, "unit": "run", "verified": True,
        "note": "GSC API (free) + DataForSEO market enrichment on the win candidates ≈ $0.05/run.",
    },
    "brand_scan": {
        "label": "AI-visibility scan (LABS)", "unit_cost": 0.02, "unit": "keyword-engine", "verified": True,
        "note": "~$0.02/cell: web-search LLM answer (GPT-5.4 ~$0.02 + tool fee, Sonnet ~$0.02, Gemini "
                "2.5 Flash ~$0.003, Perplexity Sonar ~$0.011, DataForSEO AIO ~$0.001) + GPT-5.4-mini "
                "classifier ~$0.0015, averaged across the 6 engines ≈ $0.12/keyword.",
    },
    "page_audit": {
        "label": "On-page audit (nlp 8-engine)", "unit_cost": 0.10, "unit": "page", "verified": True,
        "note": "~$0.10/page: Sonnet scoring (~8k in/4k out ≈ $0.08) + ScrapeOwl JS fetch + TextRazor "
                "entity extraction. (Scores with Sonnet, confirmed; Opus 4.8 would be ~$0.15.)",
    },
    "keyword_research": {
        "label": "Keyword research run (Topic Fanout)", "unit_cost": 0.50, "unit": "run", "verified": True,
        "note": "~$0.50/run: GPT-5.4 silo discovery (~$0.10) + dozens of ScrapeOwl fetches (~$0.06) + "
                "TextRazor entity calls (~$0.15) — variable; a heavy run can run higher.",
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
