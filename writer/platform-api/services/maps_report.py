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
import secrets
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import maps_analytics, maps_geocode, maps_image, maps_octants
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger(__name__)

# Max concurrent saved-map-image renders within one scan's job. This is a Google
# Static Maps fetch + Supabase upload per keyword — NOT an Anthropic call — so it
# is safe to keep parallel and is not throttled to the account's concurrent-
# connections limit. The per-keyword LLM narrative fan-out is capped separately by
# settings.maps_report_concurrency (see run_maps_report_job).
_IMAGE_CONCURRENCY = 5

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


def weak_area_names(weak_locations: Optional[dict], top_n: int = 8) -> list[str]:
    """Short, priority-ordered "City, ST — priority N (tier): M weak pins (octants)"
    lines from the geocoded weak areas, for naming real places in the narrative in
    target-first order. Empty when geocoding is unavailable."""
    out: list[str] = []
    for a in (weak_locations or {}).get("weak_areas", [])[:top_n]:
        city = a.get("city")
        if not city:
            continue
        where = f"{city}, {a['admin_area']}" if a.get("admin_area") else city
        octs = f" — {', '.join(a['octants'])}" if a.get("octants") else ""
        tier = f" {a['tier']}" if a.get("tier") else ""
        out.append(f"{where}: priority {a.get('priority', 0)}{tier}, {a.get('pins', 0)} weak pins{octs}")
    return out


def summarize_report_failures(
    client_name: Optional[str], failures: list[tuple[str, str]], total: int,
) -> dict:
    """Build the {title, summary, severity} digest for a report-generation-failure
    notification. `failures` is a list of (keyword, short_error). Pure; unit-tested."""
    n = len(failures)
    who = f" for {client_name}" if client_name else ""
    title = f"Local Rank report generation failed ({n}/{total})"
    keywords = ", ".join(f"“{kw}”" for kw, _ in failures[:8] if kw)
    if n > 8:
        keywords += f", +{n - 8} more"
    first_error = next((err for _, err in failures if err), "") or "unknown error"
    summary = (
        f"{n} of {total} keyword report(s) failed to generate{who}."
        + (f" Keywords: {keywords}." if keywords else "")
        + f" First error: {first_error[:200]}"
    )
    return {"title": title, "summary": summary, "severity": "warning"}


def build_snapshot(
    client: dict, result_row: dict, analytics: dict, weak_locations: Optional[dict] = None,
) -> dict:
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
        "weak_area_locations": weak_area_names(weak_locations),
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
If `weak_area_locations` is non-empty, add a short "Weakest nearby areas" bullet list naming those real towns/cities (with their weak-pin counts) so the weak zones are concrete places, not just compass directions. If it's empty, omit that list entirely (do not invent place names).

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


def _is_transient_anthropic_error(exc: Exception) -> bool:
    """True for retryable Anthropic failures: the concurrent-connections / rate
    limit 429, transient 5xx (overloaded), and connection drops. A truncated /
    empty tool-use response is also retryable (raised as RuntimeError below)."""
    import anthropic  # lazy: keep the pure rollup/snapshot helpers import-free

    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    # A max_tokens-truncated tool call yields an empty summary — worth one more try.
    return isinstance(exc, RuntimeError) and "maps_report_empty_summary" in str(exc)


async def _call_llm(snapshot: dict) -> dict:
    """Run Claude with forced tool-use; returns {summary, weak_directions,
    top_competitors}. Retries transient failures (429 concurrent-connections /
    rate limit, 5xx, connection errors) with exponential backoff + jitter so a
    burst of concurrent per-keyword calls doesn't permanently fail rows."""
    max_retries = settings.maps_report_max_retries
    base = settings.maps_report_retry_base_seconds
    attempt = 0
    while True:
        try:
            return await _call_llm_once(snapshot)
        except Exception as exc:  # noqa: BLE001 — classify then re-raise if terminal
            if attempt >= max_retries or not _is_transient_anthropic_error(exc):
                raise
            # Exponential backoff with jitter (0.5–1.5×) to de-synchronize the
            # concurrent per-keyword retries so they don't re-collide on the limit.
            delay = base * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0)
            logger.warning(
                "maps_report_llm_retry",
                extra={"attempt": attempt + 1, "delay_s": round(delay, 1), "error": str(exc)[:200]},
            )
            await asyncio.sleep(delay)
            attempt += 1


async def _call_llm_once(snapshot: dict) -> dict:
    """One forced tool-use Claude call; raises on empty/truncated output."""
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

    # Reverse-geocode the weak zones (octant pins + weak grid cells) to real city
    # names. Best-effort: a missing key/quota leaves the report otherwise intact.
    try:
        weak_locations = await maps_geocode.build_weak_locations(
            result_row.get("rank_grid") or [],
            scan_row.get("center_lat"), scan_row.get("center_lng"),
            octant_pins.get("points") or [],
            competitors_above=result_row.get("competitors_above"),
            client_reviews=(client.get("gbp") or {}).get("gbp_review_count"),
            azimuth_offset_deg=analytics.get("azimuth_offset_deg", 0.0),
            supabase=get_supabase(),
        )
    except Exception as exc:  # geocoding must never sink the report
        logger.warning("maps_weak_locations_failed", extra={"error": str(exc)})
        weak_locations = {"geocoded": False, "octant_pins": octant_pins.get("points") or [], "weak_areas": []}

    snapshot = build_snapshot(client, result_row, analytics, weak_locations)
    llm = await _call_llm(snapshot)

    return {
        "report_status": "complete",
        "report_error": None,
        "report_md": llm.get("summary"),
        "report_weak_directions": llm.get("weak_directions"),
        "report_top_competitors": llm.get("top_competitors"),
        "report_octant_pins": octant_pins,
        "report_weak_locations": weak_locations,
        "report_analytics": analytics,
        "report_generated_at": "now()",
    }


# ----------------------------------------------------------------------------
# Job + enqueue
# ----------------------------------------------------------------------------
# Concurrency + safety cap for the one-off image backfill.
_BACKFILL_CONCURRENCY = 4
_BACKFILL_MAX_ROWS = 10000


def enqueue_maps_image_backfill(client_id: str, overwrite: bool = False) -> str:
    """Enqueue a one-off per-client backfill that renders + stores the saved map
    PNG for existing scan results that predate the feature. Returns the job id.
    (async_jobs.entity_id is NOT NULL, so the backfill is always client-scoped;
    the route fans out across all clients when the caller doesn't name one.)"""
    supabase = get_supabase()
    row = (
        supabase.table("async_jobs").insert({
            "job_type": "maps_image_backfill",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "overwrite": overwrite},
        }).execute()
    ).data
    return (row[0]["id"] if row else None)


def enqueue_maps_image_backfill_all(overwrite: bool = False) -> list[str]:
    """Fan out a backfill job per client that has any geo-grid scan result.
    Returns the enqueued job ids."""
    supabase = get_supabase()
    seen: set[str] = set()
    page = 0
    while True:
        rows = (
            supabase.table("maps_scan_results").select("client_id")
            .order("client_id").range(page * 1000, page * 1000 + 999).execute()
        ).data or []
        for r in rows:
            if r.get("client_id"):
                seen.add(r["client_id"])
        if len(rows) < 1000:
            break
        page += 1
    return [jid for cid in sorted(seen) if (jid := enqueue_maps_image_backfill(cid, overwrite))]


async def run_maps_image_backfill_job(job: dict) -> None:
    """async_jobs handler for 'maps_image_backfill' — render + store the saved map
    image for existing maps_scan_results rows that have a grid but no image.

    Best-effort per row: a row that can't render (no Maps key, dead tile, upload
    failure) is left untouched and simply retried on a later run. Idempotent —
    with overwrite=False it only touches rows where map_image_url is null, so it
    can be re-run safely."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    overwrite = bool(payload.get("overwrite"))
    job_id = job["id"]
    supabase = get_supabase()
    try:
        # Collect the fixed candidate set up front (paged) so failures can't cause
        # an infinite re-fetch loop. Only rows with a usable grid are kept.
        candidates: list[dict] = []
        page = 0
        while len(candidates) < _BACKFILL_MAX_ROWS:
            q = supabase.table("maps_scan_results").select("id, scan_id, client_id, rank_grid")
            if not overwrite:
                q = q.is_("map_image_url", "null")
            if client_id:
                q = q.eq("client_id", client_id)
            batch = (
                q.order("id").range(page * 500, page * 500 + 499).execute()
            ).data or []
            if not batch:
                break
            candidates.extend(r for r in batch if _grid_ok(r.get("rank_grid")))
            if len(batch) < 500:
                break
            page += 1

        # Scan centers live on maps_scans; fetch them for the referenced scans.
        scan_ids = list({r["scan_id"] for r in candidates if r.get("scan_id")})
        centers: dict[str, tuple] = {}
        for i in range(0, len(scan_ids), 200):
            chunk = scan_ids[i:i + 200]
            rows = (
                supabase.table("maps_scans").select("id, center_lat, center_lng")
                .in_("id", chunk).execute()
            ).data or []
            for s in rows:
                centers[s["id"]] = (s.get("center_lat"), s.get("center_lng"))

        sem = asyncio.Semaphore(_BACKFILL_CONCURRENCY)

        async def _one(r: dict) -> str:
            center = centers.get(r.get("scan_id")) or (None, None)
            async with sem:
                try:
                    url = await maps_image.generate_and_store(
                        supabase, r.get("client_id"), r.get("scan_id"), r["id"],
                        r.get("rank_grid"), center[0], center[1],
                    )
                except Exception as exc:  # noqa: BLE001 — isolate per-row failure
                    logger.warning("maps_image_backfill_row_failed", extra={"result_id": r["id"], "error": str(exc)})
                    return "failed"
            if not url:
                return "skipped"
            supabase.table("maps_scan_results").update({"map_image_url": url}).eq("id", r["id"]).execute()
            return "done"

        outcomes = await asyncio.gather(*(_one(r) for r in candidates))
        done = outcomes.count("done")
        logger.info(
            "maps_image_backfill_complete",
            extra={
                "job_id": job_id, "client_id": client_id, "candidates": len(candidates),
                "done": done, "skipped": outcomes.count("skipped"), "failed": outcomes.count("failed"),
            },
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "completed_at": "now()",
             "result": {"candidates": len(candidates), "done": done,
                        "skipped": outcomes.count("skipped"), "failed": outcomes.count("failed")}}
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("maps_image_backfill_job_failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _grid_ok(grid) -> bool:
    """True when a rank_grid is a non-empty 2-D list (worth rendering)."""
    return isinstance(grid, list) and any(isinstance(row, list) and row for row in grid)


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


async def _maybe_publish_doc(
    client: dict, scan_row: dict, reports: list[tuple[str, str, Optional[str]]],
) -> Optional[str]:
    """Publish one combined Google Doc (all keyword reports) if the client has a
    Drive folder + the webhook is configured. Returns the doc_url or None.

    Each keyword's section gets a "Local Rank Map" image embedded via markdown —
    the Apps Script webhook fetches the URL and inserts a real Doc image (needs
    the image-aware markdown renderer in writer/apps-script/publish_webhook.gs; an
    older deployment renders the line as text until it's redeployed)."""
    folder_id = client.get("google_drive_folder_id")
    if not folder_id or not settings.google_apps_script_url or not reports:
        return None
    date = str(scan_row.get("completed_at") or "")[:10]
    title = f"Local Rank Analysis — {client.get('name')} — {date}".strip(" —")
    sections: list[str] = []
    for keyword, md, img_url in reports:
        if not md:
            continue
        section = md
        if img_url:
            section += f"\n\n## Local Rank Map\n\n![Local rank grid — {keyword}]({img_url})"
        sections.append(section)
    if not sections:
        return None
    body = "\n\n---\n\n".join(sections)
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

        # Render + store the saved map image per keyword FIRST, independent of the
        # LLM: the PNG (Google tile + numbered rank pins) is the archival artifact
        # and must survive a failed narrative. Best-effort, bounded, isolated —
        # keyed by result id so both the success and failed updates below can stamp
        # map_image_url and the Doc can embed it.
        img_sem = asyncio.Semaphore(_IMAGE_CONCURRENCY)

        async def _gen_image(result_row: dict) -> tuple[str, Optional[str]]:
            async with img_sem:
                try:
                    url = await maps_image.generate_and_store(
                        supabase, scan_row["client_id"], scan_id, result_row["id"],
                        result_row.get("rank_grid"),
                        scan_row.get("center_lat"), scan_row.get("center_lng"),
                    )
                    return result_row["id"], url
                except Exception as exc:  # noqa: BLE001 — a bad image never sinks the report
                    logger.warning(
                        "maps_report_image_failed",
                        extra={"scan_id": scan_id, "keyword": result_row.get("keyword"), "error": str(exc)},
                    )
                    return result_row["id"], None

        image_urls: dict[str, Optional[str]] = dict(
            await asyncio.gather(*(_gen_image(r) for r in results))
        )

        # Generate per-keyword reports concurrently (each is a ~1-min LLM call) so
        # a multi-keyword scan doesn't hold the single async-job worker for many
        # minutes serially. Capped at settings.maps_report_concurrency — kept at or
        # under the account's concurrent-connections ceiling so the per-keyword
        # calls don't collide with each other and 429 (the retry budget then only
        # has to absorb competing traffic from elsewhere in the suite, not self-
        # inflicted contention). Each keyword still fails in isolation; Supabase
        # writes (sync) are done after, off the gather.
        sem = asyncio.Semaphore(max(1, settings.maps_report_concurrency))

        async def _gen_one(result_row: dict):
            async with sem:
                try:
                    return result_row, await generate_report_for_result(client, scan_row, result_row), None
                except Exception as exc:  # noqa: BLE001 — isolate per-keyword failure
                    return result_row, None, exc

        generated: list[tuple[str, str, Optional[str]]] = []  # (keyword, markdown, image_url)
        failures: list[tuple[str, str]] = []  # (keyword, short_error)
        for result_row, fields, exc in await asyncio.gather(*(_gen_one(r) for r in results)):
            img_url = image_urls.get(result_row["id"])
            if exc is not None or fields is None:
                logger.warning(
                    "maps_report_keyword_failed",
                    extra={"scan_id": scan_id, "keyword": result_row.get("keyword"), "error": str(exc)},
                )
                failures.append((result_row.get("keyword"), str(exc)))
                # Still persist the saved map image even when the narrative failed.
                supabase.table("maps_scan_results").update(
                    {"report_status": "failed", "report_error": str(exc)[:500], "map_image_url": img_url}
                ).eq("id", result_row["id"]).execute()
                continue
            fields = {**fields, "map_image_url": img_url}
            supabase.table("maps_scan_results").update(fields).eq("id", result_row["id"]).execute()
            if fields.get("report_md"):
                generated.append((result_row.get("keyword"), fields["report_md"], img_url))

        # Surface failed report generation as a warning notification (best-effort)
        # so a silently-failed batch is visible in-app + Slack instead of only in
        # the row status. One digest per scan, never per keyword.
        if failures:
            try:
                from services import notifications

                digest = summarize_report_failures(client.get("name"), failures, len(results))
                notifications.emit(
                    client_id=scan_row.get("client_id"),
                    kind="maps_report_failed",
                    title=digest["title"],
                    summary=digest["summary"],
                    severity=digest["severity"],
                    payload={"link": f"clients/{scan_row.get('client_id')}/maps", "scan_id": scan_id},
                )
            except Exception as exc:  # notifications are best-effort
                logger.warning("maps_report_notify_failed", extra={"scan_id": scan_id, "error": str(exc)})

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
