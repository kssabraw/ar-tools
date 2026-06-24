"""Local Rank Analysis report (Maps Module #5).

Auto-generated, client-facing diagnostic for each per-keyword geo-grid scan
result. Combines:
  - deterministic rollups from `maps_analytics` (rings + octants + horizon),
  - competitor data already captured on the result (`competitors`,
    `competitors_above`) plus the client's own GBP,
  - a Claude Sonnet narrative that follows the strict report template
    (observational only — no recommendations),
  - the octant-based hyper-local pin suggestions (`maps_octants`).

Triggered as an `async_jobs` job ('maps_report') when a scan completes; the job
generates a report per keyword and publishes one combined Google Doc to the
client's Drive folder (best-effort).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import maps_analytics, maps_octants
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger(__name__)

# Max concurrent per-keyword report generations within one scan's job.
_REPORT_CONCURRENCY = 5

# Generic tokens in a keyword that aren't a brandable "name keyword" signal.
_STOPWORDS = {
    "near", "me", "best", "top", "in", "the", "and", "for", "of", "a", "service",
    "services", "company", "companies", "contractor", "contractors", "local",
}


# ----------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ----------------------------------------------------------------------------
def _is_number(v) -> bool:
    """True for real numeric values (ints/floats), excluding bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def keyword_tokens(keyword: str) -> list[str]:
    """Meaningful lowercased tokens of a keyword (drops generic/location words)."""
    words = re.findall(r"[a-z]+", (keyword or "").lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


def name_keyword_hit(name: Optional[str], tokens: list[str]) -> Optional[str]:
    """The first keyword token that appears in a competitor's GBP name, else None."""
    low = (name or "").lower()
    return next((t for t in tokens if t in low), None)


def client_sab_or_physical(gbp: Optional[dict]) -> str:
    """Best-effort: a public street address => 'Physical', else 'SAB'."""
    if gbp and (gbp.get("address") or "").strip():
        return "Physical"
    return "SAB"


def competitor_diagnostics(
    competitors: Optional[list[dict]], client_reviews: Optional[int], keyword: str,
    min_rating: float, top_n: int = 5,
) -> list[dict]:
    """Top competitors rated >= min_rating, most-reviewed first, with the review
    gap vs the client and a GBP-name-keyword flag. SAB/Physical is unknown for
    competitors (we don't capture their address) -> None."""
    tokens = keyword_tokens(keyword)
    eligible = [
        c for c in (competitors or [])
        if isinstance(c.get("rating"), (int, float)) and c["rating"] >= min_rating
    ]
    eligible.sort(key=lambda c: (-(c.get("reviews") or 0)))
    out: list[dict] = []
    for c in eligible[:top_n]:
        reviews = c.get("reviews")
        hit = name_keyword_hit(c.get("name"), tokens)
        gap = (reviews - client_reviews) if (_is_number(reviews) and _is_number(client_reviews)) else None
        out.append({
            "name": c.get("name"),
            "rating": c.get("rating"),
            "reviews": reviews,
            "main_category": c.get("primary_category"),
            "sab_physical": None,  # not captured for competitors
            "gbp_name_keyword": hit,
            "review_gap_vs_client": gap,
        })
    return out


def _grid_octant(ri: int, ci: int, n: int, azimuth_offset_deg: float = 0.0) -> Optional[str]:
    center = (n - 1) / 2
    return maps_analytics._octant_for(center - ri, ci - center, azimuth_offset_deg)


def weak_sector_competitors(
    competitors_above: Optional[dict], weak_octants: list[str], azimuth_offset_deg: float = 0.0,
    per_sector: int = 3,
) -> dict:
    """For each weak octant, the competitors that most often rank ABOVE the client
    on its pins -> {octant: [{name, place_id, pins}, ...]}."""
    if not competitors_above:
        return {}
    directory = competitors_above.get("directory") or {}
    grid = competitors_above.get("grid") or []
    n = max((len(r) for r in grid), default=0)
    tally: dict[str, dict[str, int]] = {o: {} for o in weak_octants}
    for ri, row in enumerate(grid):
        for ci, cell in enumerate(row or []):
            if not cell:  # None (out-of-circle) or [] (client ranks 1st here)
                continue
            oct_name = _grid_octant(ri, ci, n, azimuth_offset_deg)
            if oct_name not in tally:
                continue
            for entry in cell:
                pid = entry[0] if isinstance(entry, (list, tuple)) and entry else None
                if pid:
                    tally[oct_name][pid] = tally[oct_name].get(pid, 0) + 1
    out: dict[str, list] = {}
    for oct_name, counts in tally.items():
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:per_sector]
        out[oct_name] = [
            {"place_id": pid, "name": (directory.get(pid) or {}).get("name"), "pins": pins}
            for pid, pins in ranked
        ]
    return out


def build_snapshot(client: dict, result_row: dict, analytics: dict) -> dict:
    """The full data snapshot handed to the LLM (and reused for the Doc)."""
    gbp = client.get("gbp") or {}
    keyword = result_row.get("keyword")
    client_reviews = gbp.get("gbp_review_count")
    diags = competitor_diagnostics(
        result_row.get("competitors"), client_reviews, keyword,
        settings.maps_report_competitor_min_rating,
    )
    weak = [d["sector"] for d in analytics.get("weakest_directions", [])]
    notes = weak_sector_competitors(
        result_row.get("competitors_above"), weak, analytics.get("azimuth_offset_deg", 0.0),
    )
    return {
        "client": {
            "name": client.get("name"),
            "keyword": keyword,
            "rating": gbp.get("gbp_rating"),
            "review_count": client_reviews,
            "primary_category": gbp.get("gbp_category"),
            "sab_physical": client_sab_or_physical(gbp),
        },
        "overall": analytics.get("overall"),
        "performance_horizon": analytics.get("performance_horizon"),
        "best_directions": analytics.get("best_directions"),
        "weakest_directions": analytics.get("weakest_directions"),
        "ring_summaries": [
            {k: r[k] for k in (
                "ring", "radius_mi", "avg_rank", "coverage_pct_top3",
                "coverage_pct_top10", "cells", "ranked", "not_ranked")}
            for r in analytics.get("ring_summaries", [])
        ],
        "sectors_overall": analytics.get("sectors_overall"),
        "competitor_top5": diags,
        "weak_sector_competitors": notes,
    }


SYSTEM_PROMPT = (
    "You are an expert local SEO analyst. You produce a concise, data-driven, "
    "client-friendly diagnostic of local search ranking performance from GeoGrid "
    "heatmap rollups and competitor GBP data. You ANALYZE ONLY — never prescribe "
    "fixes, recommendations, or next steps. Use ONLY the numbers present in the "
    "provided JSON; if a figure is missing show “—” and state "
    "“insufficient data” briefly. Round numbers to 1–2 decimals."
)


def build_user_prompt(snapshot: dict) -> str:
    """The strict report instructions + the data snapshot."""
    data = json.dumps(snapshot, indent=2, default=str)
    name = snapshot["client"]["name"]
    keyword = snapshot["client"]["keyword"]
    return f"""Generate a Local Rank Analysis report for the client below.

DATA (use only these numbers):
{data}

Return the ENTIRE report as Markdown in the `summary` field of the emit_report
tool, following EXACTLY this structure and order (omit any "source/map link"):

# Local Rank Analysis — {name}

**Keyword:** “{keyword}”

## Overview
2–3 plain-English sentences for a non-technical reader: the overall local visibility picture — where the business is strong, where it fades, and the single biggest competitive pressure. No jargon, no numbers-dump.

## Key Strengths Recap
Bullets: proximity performance, directional patterns, review signals, category relevance, visibility baseline, anchor opportunities. Then a short summarizing paragraph of the positives.

## Executive Summary
* **Average Rank (overall)**
* **Top-3 Coverage** (overall coverage_pct_top3)
* **Top-10 Coverage** (overall coverage_pct_top10)
* **Performance horizon** — the distance ring where rank / Top-3 coverage collapses.
* **Best directions** (lowest avg rank) and **weakest directions** (highest avg rank).

\U0001F4CD **Performance Horizon Callout:** state the ring (in miles) where visibility drops sharply.

### Narrative (Radius & Direction)
4–7 sentences: visibility close to the business (inner rings), how it changes mid/outer distance, and which compass directions feel familiar/visible vs fading — grounded in the actual numbers.

## Performance by Distance (Radius)
A table with columns: Distance (mi) | Avg. Rank | Top-3 Coverage — one row per ring from ring_summaries.
*Legend: “Top-3 Coverage” = % of search points where the business shows in the top 3 (the Map Pack).*
Then 3–5 sentences summarizing the distance story; restate the performance horizon.

## Geographic Strengths (Directions)
Top 2–3 strongest sectors (lowest avg_rank) from sectors_overall, as bullets with avg rank values. Then 2–4 sentences.

## Geographic Weaknesses (Directions & Distance)
Weakest sectors (highest avg_rank) from sectors_overall; flag any with Top-3 coverage < 20%. Note the ring(s) where performance degrades most, with simple decay bullets per direction.

### Competitor Notes (Who Beats You Here)
For each weak sector, the competitors that consistently rank higher (from weak_sector_competitors), as a scannable bullet list. Then 3–5 sentences tying weak zones to those competitors' advantages (review volume, category, name keywords).

## Competitive Landscape
### High-Level View
A table of the Top 5 competitors by reviews: # | Competitor | Rating | Reviews (from competitor_top5). Then 1–3 bullets naming which dominate weak zones, and 1–2 sentences on how review-rich competitors act like “billboards.”
### Competitor Diagnostic Add-On (Detailed)
A table: # | Competitor | SAB/Physical | GBP Name Keyword? | Main Category | Rating | Reviews | Review Gap vs Client (from competitor_top5; SAB/Physical is “— (insufficient data)” for competitors).
## Competitive Landscape Snapshot
1–2 sentences on how SAB/physical mix, name keyword usage, review strength, and category alignment shape performance (client SAB/Physical = {snapshot['client']['sab_physical']}).

## Review Profile Comparison
Client rating + total reviews vs the Top-5 competitor review min–max. Then 2–4 sentences on quality vs quantity in contested areas.

Also populate:
- `weak_directions`: a concise paragraph or short bullet list naming the weakest sectors and the ring(s) where degradation begins.
- `top_competitors`: an array of up to 5 short strings, one per Top-5 competitor (name — rating — reviews).
"""


_EMIT_TOOL = {
    "name": "emit_report",
    "description": "Emit the finished Local Rank Analysis report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "The full report in Markdown."},
            "weak_directions": {"type": "string", "description": "Weakest sectors + degradation rings."},
            "top_competitors": {
                "type": "array", "items": {"type": "string"},
                "description": "Up to 5 short competitor lines.",
            },
        },
        "required": ["summary", "weak_directions", "top_competitors"],
    },
}


async def _call_llm(snapshot: dict) -> dict:
    """Run Claude with forced tool-use; returns {summary, weak_directions, top_competitors}."""
    import anthropic  # lazy: keep the pure rollup/snapshot helpers import-free

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.maps_report_model,
        max_tokens=settings.maps_report_max_tokens,
        system=SYSTEM_PROMPT,
        tools=[_EMIT_TOOL],
        tool_choice={"type": "tool", "name": "emit_report"},
        messages=[{"role": "user", "content": build_user_prompt(snapshot)}],
    )
    out = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_report":
            out = block.input or {}
            break
    if out is None:
        raise RuntimeError(f"maps_report_llm_no_tool_use (stop={response.stop_reason})")
    # A truncated tool-use response (e.g. stop_reason='max_tokens') yields an
    # empty/partial input and no usable summary — fail loudly so it's retryable
    # rather than silently storing an empty "complete" report.
    if not (out.get("summary") or "").strip():
        raise RuntimeError(f"maps_report_empty_summary (stop={response.stop_reason})")
    return out


# ----------------------------------------------------------------------------
# Per-result generation
# ----------------------------------------------------------------------------
async def generate_report_for_result(client: dict, scan_row: dict, result_row: dict) -> dict:
    """Build the analytics + octant pins, run the LLM, and return the column
    values to persist on the result row (does not write)."""
    analytics = maps_analytics.build_geogrid_analytics(result_row.get("rank_grid") or [])

    # Octant pin generator, fed the deterministic weakest octants as the override.
    heatmap = {
        "center": {"lat": scan_row.get("center_lat"), "lng": scan_row.get("center_lng")},
        "azimuth_offset_deg": analytics.get("azimuth_offset_deg", 0.0),
        "ring_summaries": analytics.get("ring_summaries", []),
        "sectors_overall": analytics.get("sectors_overall", []),
    }
    weak = [d["sector"] for d in analytics.get("weakest_directions", [])]
    try:
        octant_pins = maps_octants.select_octant_pins(
            heatmap, settings.maps_report_octant_rule, weak_octants=weak,
        )
    except Exception as exc:  # never let pin math sink the report
        logger.warning("maps_octant_pins_failed", extra={"error": str(exc)})
        octant_pins = {"ok": False, "reason": f"octant_error: {exc}", "points": []}

    snapshot = build_snapshot(client, result_row, analytics)
    llm = await _call_llm(snapshot)

    return {
        "report_status": "complete",
        "report_error": None,
        "report_md": llm.get("summary"),
        "report_weak_directions": llm.get("weak_directions"),
        "report_top_competitors": llm.get("top_competitors"),
        "report_octant_pins": octant_pins,
        "report_analytics": analytics,
        "report_generated_at": "now()",
    }


# ----------------------------------------------------------------------------
# Job + enqueue
# ----------------------------------------------------------------------------
def enqueue_maps_report(scan_id: str) -> bool:
    """Enqueue report generation for a completed scan (deduped)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "maps_report").eq("entity_id", scan_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    # Reflect the queued state immediately so the UI shows "Generating…" on the
    # next refetch (the job flips each row to complete/failed as it finishes).
    supabase.table("maps_scan_results").update(
        {"report_status": "pending", "report_error": None}
    ).eq("scan_id", scan_id).execute()
    supabase.table("async_jobs").insert(
        {"job_type": "maps_report", "entity_id": scan_id, "payload": {"scan_id": scan_id}}
    ).execute()
    return True


async def _maybe_publish_doc(client: dict, scan_row: dict, reports: list[tuple[str, str]]) -> Optional[str]:
    """Publish one combined Google Doc (all keyword reports) if the client has a
    Drive folder + the webhook is configured. Returns the doc_url or None."""
    folder_id = client.get("google_drive_folder_id")
    if not folder_id or not settings.google_apps_script_url or not reports:
        return None
    date = str(scan_row.get("completed_at") or "")[:10]
    title = f"Local Rank Analysis — {client.get('name')} — {date}".strip(" —")
    body = "\n\n---\n\n".join(md for _, md in reports if md)
    try:
        result = await create_google_doc(folder_id, title, body)
        return result.get("doc_url")
    except GoogleDocError as exc:
        logger.warning("maps_report_doc_publish_failed", extra={"scan_id": scan_row.get("id"), "error": str(exc)})
        return None


async def run_maps_report_job(job: dict) -> None:
    """async_jobs handler for 'maps_report' — generate a report per keyword for a
    completed scan, then publish one combined Doc."""
    payload = job.get("payload") or {}
    scan_id = payload.get("scan_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        scan_row = (
            supabase.table("maps_scans").select("*").eq("id", scan_id).single().execute()
        ).data
        if not scan_row:
            raise RuntimeError("scan_not_found")
        client = (
            supabase.table("clients").select("id, name, gbp, google_drive_folder_id")
            .eq("id", scan_row["client_id"]).single().execute()
        ).data or {}
        results = (
            supabase.table("maps_scan_results")
            .select("id, keyword, rank_grid, competitors, competitors_above")
            .eq("scan_id", scan_id).execute()
        ).data or []

        # Generate per-keyword reports concurrently (each is a ~1-min LLM call) so
        # a multi-keyword scan doesn't hold the single async-job worker for many
        # minutes serially. Bounded so a large keyword set can't fan out an
        # unbounded burst of Anthropic calls. Each keyword still fails in
        # isolation; Supabase writes (sync) are done after, off the gather.
        sem = asyncio.Semaphore(_REPORT_CONCURRENCY)

        async def _gen_one(result_row: dict):
            async with sem:
                try:
                    return result_row, await generate_report_for_result(client, scan_row, result_row), None
                except Exception as exc:  # noqa: BLE001 — isolate per-keyword failure
                    return result_row, None, exc

        generated: list[tuple[str, str]] = []  # (keyword, markdown)
        for result_row, fields, exc in await asyncio.gather(*(_gen_one(r) for r in results)):
            if exc is not None or fields is None:
                logger.warning(
                    "maps_report_keyword_failed",
                    extra={"scan_id": scan_id, "keyword": result_row.get("keyword"), "error": str(exc)},
                )
                supabase.table("maps_scan_results").update(
                    {"report_status": "failed", "report_error": str(exc)[:500]}
                ).eq("id", result_row["id"]).execute()
                continue
            supabase.table("maps_scan_results").update(fields).eq("id", result_row["id"]).execute()
            if fields.get("report_md"):
                generated.append((result_row.get("keyword"), fields["report_md"]))

        doc_url = await _maybe_publish_doc(client, scan_row, generated)
        if doc_url:
            supabase.table("maps_scan_results").update({"report_doc_url": doc_url}).eq(
                "scan_id", scan_id
            ).execute()

        supabase.table("async_jobs").update(
            {"status": "complete", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("maps_report_complete", extra={"scan_id": scan_id, "keywords": len(generated)})
    except Exception as exc:
        logger.error("maps_report_job_failed", extra={"scan_id": scan_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
