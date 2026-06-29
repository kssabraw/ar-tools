"""Reoptimization planner — turns the rank tracker's signals into a ranked,
client-scoped list of recommended actions, each with a deep link into the tool
that does it.

Signals (all reads we already produce):
  - open rank-drop alerts (rank_alerts)         → "diagnose & reoptimize" / "confirm indexing"
  - rankability Quick wins (services.rankability)→ "reoptimize the page" / "create a page"
  - GSC-Research opportunities (gsc_research_runs):
        cannibalization → "consolidate/canonicalize"
        hidden wins     → "refresh & expand to reach page 1"
  - Maps geo-grid declines (maps_alerts)        → "diagnose & strengthen local signals"
        + competitor surges, geocoded weak coverage areas
          (maps_scan_results.report_weak_locations) → "create a location page",
          and a Share-of-Local-Voice drop (scan-over-scan) → "win back local share"
  - Brand-search decline (gsc_query_daily)      → "invest in brand-building"

build_actions (organic, pure) + build_maps_actions (local-pack, pure) do the
diagnosis→action mapping + ranking; build_plan does the reads, merges both
sources under one cap, stores a reopt_plans row, and (on the weekly cadence)
pushes a digest through the notifications service. Maps drops trigger a silent
rebuild (trigger="maps_drop") that rides the maps_drop alert. Recommend-only —
every action routes a human into an existing tool; nothing is auto-executed.
"""

from __future__ import annotations

import logging

from db.supabase_client import get_supabase
from services import notifications, rankability

logger = logging.getLogger(__name__)

# Tuning (module constants).
QUICK_WIN_BANDS = {"Easy", "Moderate"}
QUICK_WIN_MIN_SCORE = 50
QUICK_WIN_MAX = 10
CANNIBAL_MAX = 5
HIDDEN_MAX = 8
STRIKING_DISTANCE_MAX = 20  # client_rank ≤ this → reoptimize existing vs create new
TOTAL_MAX = 25

# Sort is tiered: a category base keeps the kinds in a strict priority order
# (organic drops → cannibalization → local-pack declines → quick wins → hidden
# wins), and a bounded within-tier term ranks members of the same kind by their
# own signal strength without ever crossing into the next tier. (A huge-value
# quick win must not leapfrog an urgent drop, and same-kind rows must not all tie.)
_TIER = 10_000
_WITHIN_MAX = 9_999          # within-tier term is clamped to [0, _WITHIN_MAX]
_SORT_DROP = 6 * _TIER
_SORT_DEINDEX_BONUS = _TIER  # deindex sits in its own band above ordinary drops
_SORT_CANNIBAL = 4 * _TIER
_SORT_MAPS = 3 * _TIER       # local-pack declines: below cannibalization, above quick wins
_SORT_QUICK = 2 * _TIER
_SORT_HIDDEN = 1 * _TIER

# Within-tier base rank for each Maps alert type (then nudged by signal strength).
_MAPS_WITHIN = {
    "lost_pack": 9_000,       # fell out of the local pack — most urgent (also critical severity)
    "grid_rank_drop": 6_000,
    "coverage_drop": 6_000,
    "competitor_surge": 5_000,
    "area_decline": 3_000,
}
_MAPS_WEAK_AREA_WITHIN = 1_000  # weak coverage areas sit at the bottom of the Maps tier
_MAPS_GBP_WITHIN = 4_000        # a GBP-gap action sits mid Maps tier (above weak areas)
_MAPS_SOLV_WITHIN = 8_500       # a SoLV drop sits near the top of the Maps tier (just under lost_pack)
MAPS_WEAK_AREA_MAX = 5          # cap weak-area actions per plan
SOLV_DROP_MIN_PCT = 10.0        # min Top-3 local-pack share lost (points) to flag a SoLV drop

# Brand-search health (organic). A relative drop in branded impressions, recent
# window vs prior window, signals softening brand demand.
_SORT_BRAND = 1 * _TIER         # hidden-win tier; bumped to the top of it via within
_BRAND_WITHIN = 9_500
BRAND_DECLINE_MIN_PCT = 25.0    # min relative % fall in branded impressions to flag

# Full compass-octant labels for human-readable sector text.
_OCTANT_FULL = {
    "N": "north", "NE": "northeast", "E": "east", "SE": "southeast",
    "S": "south", "SW": "southwest", "W": "west", "NW": "northwest",
}


def _within(value: float) -> float:
    """Clamp a within-tier ranking term so it can't bleed into another tier."""
    return max(0.0, min(float(value), _WITHIN_MAX))


def _should_store(action_count: int, latest_action_count: "int | None") -> bool:
    """Whether to persist a freshly-built plan as a new row. Pure (unit-tested).

    Always store a non-empty plan, and always store the *transition* to empty
    (so 'latest plan' reflects that the actions cleared). Skip only the steady
    state — an empty build when the latest stored plan is already empty — so a
    healthy client doesn't accumulate one identical no-op row per weekly run.
    """
    if action_count > 0:
        return True
    return latest_action_count is None or latest_action_count > 0


def _plan_path(client_id: str) -> str:
    return f"clients/{client_id}/action-plan"


def build_actions(
    client_id: str,
    drops: list[dict],
    rankability_items: list[dict],
    gsc: dict,
    cap: "int | None" = TOTAL_MAX,
) -> list[dict]:
    """Map the organic-search signals to a ranked, deduped action list. Pure
    (unit-tested). `cap` bounds the result; pass None to return the full sorted
    list (build_plan does this so Maps actions can compete for the combined cap)."""
    actions: list[dict] = []
    dropped_keywords: set[str] = set()

    # 1) Open rank-drop alerts — urgent.
    for d in drops:
        kw = d.get("keyword") or ""
        dropped_keywords.add(kw.lower())
        deindex = d.get("alert_type") == "deindexed"
        actions.append(
            {
                "kind": "rank_drop",
                "source": "organic",
                "keyword": kw,
                "diagnosis": d.get("message") or "Ranking dropped.",
                "recommendation": (
                    "Confirm indexing — run URL Inspection and check robots/noindex/canonical, then resubmit."
                    if deindex
                    else "Diagnose & reoptimize — capture a SERP snapshot to see what changed (AI Overview, "
                    "a stronger competitor, an intent shift), then reoptimize the ranking page."
                ),
                "cta_label": "Open rank tracker",
                "cta_path": f"clients/{client_id}/rankings",
                "severity": "critical" if deindex else "warning",
                "sort": _SORT_DROP + (_SORT_DEINDEX_BONUS if deindex else 0),
            }
        )

    # 2) Rankability Quick wins — winnable + valuable (skip keywords already
    # surfaced as a drop; the drop action supersedes).
    winnable = [
        i for i in rankability_items
        if i.get("has_snapshot") and i.get("score") is not None
        and i.get("band") in QUICK_WIN_BANDS and i["score"] >= QUICK_WIN_MIN_SCORE
        and (i.get("keyword") or "").lower() not in dropped_keywords
    ]
    winnable.sort(key=lambda i: (i.get("priority") or 0, i["score"]), reverse=True)
    for i in winnable[:QUICK_WIN_MAX]:
        rank = i.get("client_rank")
        striking = rank is not None and rank <= STRIKING_DISTANCE_MAX
        value = i.get("est_value")
        value_str = f" · est. ${round(value):,}/mo" if value else ""
        actions.append(
            {
                "kind": "quick_win",
                "source": "organic",
                "keyword": i.get("keyword") or "",
                "diagnosis": f"Rankability {i['band']} ({i['score']}/100){value_str}.",
                "recommendation": (
                    f"Reoptimize the existing page — you're #{rank} and this SERP is winnable."
                    if striking
                    else "Create a purpose-built page — the SERP is winnable and you don't have a strong page yet."
                ),
                "cta_label": "Reoptimize" if striking else "Create page",
                "cta_path": f"clients/{client_id}/local-seo",
                "severity": "info",
                "sort": _SORT_QUICK + _within(i.get("priority") or i["score"]),
            }
        )

    # 3) GSC-Research cannibalization — wasted authority across split pages.
    for c in (gsc.get("cannibalization") or [])[:CANNIBAL_MAX]:
        actions.append(
            {
                "kind": "cannibalization",
                "source": "organic",
                "keyword": c.get("query") or "",
                "diagnosis": f"{c.get('page_count', 0)} pages split this query "
                f"({c.get('total_impressions', 0):,} impressions).",
                "recommendation": "Consolidate — pick the canonical page, 301/canonical the rest, "
                "and concentrate internal links so Google can rank one.",
                "cta_label": "GSC Research",
                "cta_path": f"clients/{client_id}/gsc-research",
                "severity": "warning",
                "sort": _SORT_CANNIBAL + _within(c.get("total_impressions") or 0),
            }
        )

    # 4) GSC-Research hidden wins — page-2 terms with demand.
    for h in (gsc.get("hidden_wins") or [])[:HIDDEN_MAX]:
        kw = h.get("keyword") or ""
        if kw.lower() in dropped_keywords:
            continue
        pos = h.get("position")
        actions.append(
            {
                "kind": "opportunity",
                "source": "organic",
                "keyword": kw,
                "diagnosis": f"Position {round(pos) if pos else '—'} with {h.get('impressions', 0):,} "
                "impressions — sitting on page 2.",
                "recommendation": "Refresh & expand the page (more depth, internal links, freshness) "
                "to push it onto page 1.",
                "cta_label": "GSC Research",
                "cta_path": f"clients/{client_id}/gsc-research",
                "severity": "info",
                "sort": _SORT_HIDDEN + _within(h.get("impressions") or 0),
            }
        )

    actions.sort(key=lambda a: a["sort"], reverse=True)
    return actions if cap is None else actions[:cap]


def build_maps_actions(
    client_id: str,
    maps_alerts: list[dict],
    weak_areas: list[dict],
    solv_drop: "dict | None" = None,
) -> list[dict]:
    """Map the local-pack (Maps geo-grid) signals to ranked actions. Pure
    (unit-tested). Emits the same action dict shape as build_actions, tagged
    source="maps", with new kinds (maps_decline / maps_competitor /
    maps_weak_area / maps_solv_drop). Local-pack declines are NOT deduped against
    organic rank drops: the web SERP and the local pack are distinct channels
    with distinct fixes, so a keyword can legitimately need both."""
    actions: list[dict] = []
    maps_path = f"clients/{client_id}/maps"

    # 0) Share of Local Voice decline — the headline "losing the local market" signal.
    if solv_drop:
        gainer = solv_drop.get("top_gainer")
        from_pct = solv_drop.get("from_pct")
        to_pct = solv_drop.get("to_pct")
        actions.append(
            {
                "kind": "maps_solv_drop",
                "source": "maps",
                "keyword": "Local market share",
                "diagnosis": f"Top-3 local-pack share fell from {from_pct}% to {to_pct}%"
                + (f" — {gainer} gained ground." if gainer else "."),
                "recommendation": "You're losing share of the local pack. Strengthen GBP signals (posts, "
                "categories, reviews) and location-page content across the grid; review the SoLV trend and "
                "competitor gains in the Maps tracker.",
                "cta_label": "Open Maps tracker",
                "cta_path": maps_path,
                "severity": "warning",
                "sort": _SORT_MAPS + _within(_MAPS_SOLV_WITHIN),
            }
        )

    # 1) Open Maps alerts (already episode-deduped in the maps_alerts table).
    for a in maps_alerts:
        alert_type = a.get("alert_type") or ""
        sector = a.get("sector")
        sector_label = f" ({_OCTANT_FULL.get(sector, sector)})" if sector else ""
        keyword = (a.get("keyword") or "") + sector_label
        message = a.get("message") or "Local-pack visibility weakened."
        within = _MAPS_WITHIN.get(alert_type, 4_000)

        if alert_type == "competitor_surge":
            actions.append(
                {
                    "kind": "maps_competitor",
                    "source": "maps",
                    "keyword": keyword,
                    "diagnosis": message,
                    "recommendation": "A competitor is newly outranking you across the grid. Review their GBP "
                    "profile (primary category, review count/velocity, photos, posts) and close the gaps.",
                    "cta_label": "Open Maps tracker",
                    "cta_path": maps_path,
                    "severity": "warning",
                    "sort": _SORT_MAPS + _within(within),
                }
            )
            continue

        lost = alert_type == "lost_pack"
        actions.append(
            {
                "kind": "maps_decline",
                "source": "maps",
                "keyword": keyword,
                "diagnosis": message,
                "recommendation": (
                    "You've dropped out of the local pack here. Diagnose in the geo-grid, then strengthen "
                    "local signals — GBP posts/categories, proximity-relevant reviews, and location-page content."
                    if lost
                    else "Local-pack visibility is slipping. Diagnose what changed in the geo-grid, then "
                    "reinforce local relevance (GBP category/services, reviews, location-page content)."
                ),
                "cta_label": "Open Maps tracker",
                "cta_path": maps_path,
                "severity": "critical" if lost else "warning",
                "sort": _SORT_MAPS + _within(within),
            }
        )

    # 2) Geocoded weak coverage areas — places to target with a location page.
    for w in (weak_areas or [])[:MAPS_WEAK_AREA_MAX]:
        city = w.get("city") or "a nearby area"
        admin = w.get("admin_area")
        place = f"{city}, {admin}" if admin else city
        pins = w.get("pins") or 0
        actions.append(
            {
                "kind": "maps_weak_area",
                "source": "maps",
                "keyword": place,
                "diagnosis": f"Weak coverage near {place} ({pins} grid pin{'s' if pins != 1 else ''}).",
                "recommendation": f"Create or strengthen a location page targeting {city} to build local "
                "relevance where the grid is weakest.",
                "cta_label": "Create page",
                "cta_path": f"clients/{client_id}/local-seo",
                "severity": "info",
                "sort": _SORT_MAPS + _within(_MAPS_WEAK_AREA_WITHIN + min(pins, 900)),
            }
        )

    actions.sort(key=lambda a: a["sort"], reverse=True)
    return actions


def build_gbp_action(client_id: str, gbp_audit_result: "dict | None") -> list[dict]:
    """A single consolidated 'strengthen your GBP' action from the profile audit
    (missing fields + category gaps + a review deficit vs competitors). Pure."""
    a = gbp_audit_result
    if not a:
        return []
    parts: list[str] = []
    if a.get("gaps"):
        parts.append("complete " + ", ".join(g.lower() for g in a["gaps"][:3]))
    if a.get("category_gaps"):
        parts.append(f"add categories ({', '.join(a['category_gaps'][:2])})")
    rg = a.get("review_gap")
    if rg and rg.get("deficit"):
        parts.append(f"close a ~{rg['deficit']}-review gap vs competitors")
    if not parts:
        return []
    score = a.get("score")
    return [
        {
            "kind": "gbp_gap",
            "source": "maps",
            "keyword": "Google Business Profile",
            "diagnosis": f"GBP completeness {score}/100 vs {a.get('competitor_count', 0)} competitors."
            if score is not None else "GBP has optimization gaps vs competitors.",
            "recommendation": "Strengthen the Google Business Profile: " + "; ".join(parts) + ".",
            "cta_label": "Open Maps tracker",
            "cta_path": f"clients/{client_id}/maps",
            "severity": "info",
            "sort": _SORT_MAPS + _within(_MAPS_GBP_WITHIN),
        }
    ]


def build_brand_action(client_id: str, brand_decline: "dict | None") -> list[dict]:
    """A brand-search-health action when branded GSC demand is falling. Pure."""
    if not brand_decline:
        return []
    return [
        {
            "kind": "brand_search_decline",
            "source": "organic",
            "keyword": "Branded search demand",
            "diagnosis": f"Branded searches fell {brand_decline.get('delta_pct')}% over the last "
            f"{brand_decline.get('weeks')} weeks vs the prior {brand_decline.get('weeks')}.",
            "recommendation": "Brand demand is softening. Invest in brand-building & reputation — reviews, "
            "PR/mentions, branded campaigns — and check for a tracking or seasonality cause first.",
            "cta_label": "Open rank tracker",
            "cta_path": f"clients/{client_id}/rankings",
            "severity": "info",
            "sort": _SORT_BRAND + _within(_BRAND_WITHIN),
        }
    ]


def summarize_plan(actions: list[dict]) -> dict:
    """{summary, severity} for the plan + its notification. Pure."""
    by_kind: dict[str, int] = {}
    for a in actions:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
    parts = []
    if by_kind.get("rank_drop"):
        n = by_kind["rank_drop"]
        parts.append(f"{n} drop{'s' if n != 1 else ''} to fix")
    wins = by_kind.get("quick_win", 0)
    if wins:
        parts.append(f"{wins} quick win{'s' if wins != 1 else ''}")
    maps = (
        by_kind.get("maps_decline", 0)
        + by_kind.get("maps_competitor", 0)
        + by_kind.get("maps_weak_area", 0)
        + by_kind.get("maps_solv_drop", 0)
        + by_kind.get("gbp_gap", 0)
    )
    if maps:
        parts.append(f"{maps} local-pack issue{'s' if maps != 1 else ''}")
    other = (
        by_kind.get("cannibalization", 0)
        + by_kind.get("opportunity", 0)
        + by_kind.get("brand_search_decline", 0)
    )
    if other:
        parts.append(f"{other} other opportunit{'ies' if other != 1 else 'y'}")
    summary = ", ".join(parts) if parts else "No actions right now — rankings look healthy."
    severities = {a["severity"] for a in actions}
    severity = "critical" if "critical" in severities else "warning" if "warning" in severities else "info"
    return {"summary": summary, "severity": severity}


# ----------------------------------------------------------------------------
# DB assembly + persistence.
# ----------------------------------------------------------------------------
def _fetch_maps_signals(supabase, client_id: str) -> "tuple[list[dict], list[dict], dict | None]":
    """Read the Maps geo-grid signals for the Action Plan: open maps_alerts, the
    latest completed scan's geocoded weak coverage areas (deduped by place,
    worst-first), and a Share-of-Local-Voice drop between the two most recent
    scans. Best-effort — any failure yields empty signals so the rest of the plan
    is unaffected."""
    try:
        alerts = (
            supabase.table("maps_alerts")
            .select("keyword, alert_type, sector, message, details")
            .eq("client_id", client_id)
            .is_("resolved_at", "null")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("reopt_plan_maps_alerts_failed", extra={"client_id": client_id, "error": str(exc)})
        alerts = []

    weak_areas: list[dict] = []
    solv_drop: "dict | None" = None
    try:
        scans = (
            supabase.table("maps_scans")
            .select("id")
            .eq("client_id", client_id)
            .eq("status", "complete")
            .order("completed_at", desc=True)
            .limit(2)
            .execute()
        ).data or []
        if scans:
            latest_rows = (
                supabase.table("maps_scan_results")
                .select("report_weak_locations, total_pins, top3_pins, top10_pins, competitors")
                .eq("scan_id", scans[0]["id"])
                .execute()
            ).data or []
            weak_areas = _aggregate_weak_areas(latest_rows)
            if len(scans) >= 2:
                from services import maps_solv

                prev_rows = (
                    supabase.table("maps_scan_results")
                    .select("total_pins, top3_pins, top10_pins, competitors")
                    .eq("scan_id", scans[1]["id"])
                    .execute()
                ).data or []
                solv_drop = maps_solv.detect_solv_drop(latest_rows, prev_rows, SOLV_DROP_MIN_PCT)
    except Exception as exc:
        logger.warning("reopt_plan_maps_signals_failed", extra={"client_id": client_id, "error": str(exc)})
        weak_areas, solv_drop = weak_areas, None

    return alerts, weak_areas, solv_drop


def _aggregate_weak_areas(results: list[dict]) -> list[dict]:
    """Flatten per-keyword weak coverage areas across a scan's results, dedup by
    (city, admin_area) keeping the entry with the most weak pins, worst-first.
    Pure (unit-tested)."""
    best: dict[tuple, dict] = {}
    for r in results:
        loc = r.get("report_weak_locations") or {}
        for area in loc.get("weak_areas") or []:
            key = ((area.get("city") or "").lower(), (area.get("admin_area") or "").lower())
            if not key[0]:
                continue
            existing = best.get(key)
            if existing is None or (area.get("pins") or 0) > (existing.get("pins") or 0):
                best[key] = area
    return sorted(best.values(), key=lambda a: a.get("pins") or 0, reverse=True)


def _fetch_gbp_audit(supabase, client_id: str) -> "dict | None":
    """Best-effort GBP audit (client GBP vs captured competitor profiles)."""
    try:
        from services import competitor_gbp, gbp_audit

        rows = supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute().data
        gbp = (rows[0].get("gbp") if rows else None) or {}
        if not gbp:
            return None
        profiles = competitor_gbp.latest_profiles(client_id)
        return gbp_audit.audit(gbp, profiles)
    except Exception as exc:
        logger.warning("reopt_plan_gbp_audit_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _fetch_brand_decline(supabase, client_id: str) -> "dict | None":
    """Best-effort brand-search decline signal (branded GSC impressions falling)."""
    try:
        from services import brand_search

        out = brand_search.load_brand_series(supabase, client_id, days=90)
        if not out.get("gsc_connected"):
            return None
        return brand_search.detect_brand_decline(out.get("series") or [], BRAND_DECLINE_MIN_PCT)
    except Exception as exc:
        logger.warning("reopt_plan_brand_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def build_plan(client_id: str, trigger: str = "manual") -> dict:
    """Gather signals, build the ranked plan, store it, and (on the weekly
    cadence) push a digest notification. Returns the stored plan summary."""
    supabase = get_supabase()

    drops = (
        supabase.table("rank_alerts")
        .select("keyword_id, keyword, alert_type, message")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []

    try:
        rankability_items = rankability.get_client_rankability(client_id).get("items", [])
    except Exception as exc:  # rankability is best-effort input
        logger.warning("reopt_plan_rankability_failed", extra={"client_id": client_id, "error": str(exc)})
        rankability_items = []

    gsc_row = (
        supabase.table("gsc_research_runs")
        .select("cannibalization, hidden_wins, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    gsc = gsc_row[0] if gsc_row else {}

    maps_alerts, weak_areas, solv_drop = _fetch_maps_signals(supabase, client_id)
    brand_decline = _fetch_brand_decline(supabase, client_id)
    gbp_audit_result = _fetch_gbp_audit(supabase, client_id)

    # Build organic uncapped so Maps actions compete fairly for the combined cap.
    organic = build_actions(client_id, drops, rankability_items, gsc, cap=None)
    maps_actions = build_maps_actions(client_id, maps_alerts, weak_areas, solv_drop)
    maps_actions += build_gbp_action(client_id, gbp_audit_result)
    brand_actions = build_brand_action(client_id, brand_decline)
    actions = organic + maps_actions + brand_actions
    actions.sort(key=lambda a: a["sort"], reverse=True)
    actions = actions[:TOTAL_MAX]
    digest = summarize_plan(actions)

    latest = (
        supabase.table("reopt_plans")
        .select("id, action_count")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    latest_count = latest[0]["action_count"] if latest else None

    if _should_store(len(actions), latest_count):
        plan = (
            supabase.table("reopt_plans")
            .insert(
                {
                    "client_id": client_id,
                    "trigger": trigger,
                    "summary": digest["summary"],
                    "items": actions,
                    "action_count": len(actions),
                }
            )
            .execute()
        ).data[0]
    else:
        # Steady-state healthy client: reuse the existing empty plan rather than
        # writing another identical no-op row.
        plan = latest[0]

    # Notify only the routine weekly digest — an on-drop refresh rides the
    # rank-drop notification that already fired; a manual run means the user is
    # already looking. Don't ping for an empty plan.
    if trigger == "scheduled" and actions:
        notifications.emit(
            client_id=client_id,
            kind="reopt_plan",
            title=f"Action plan: {len(actions)} recommendation{'s' if len(actions) != 1 else ''}",
            summary=digest["summary"],
            severity=digest["severity"],
            payload={"link": _plan_path(client_id), "plan_id": plan["id"]},
        )

    logger.info(
        "reopt_plan_built",
        extra={"client_id": client_id, "trigger": trigger, "actions": len(actions)},
    )
    return {"plan_id": plan["id"], "action_count": len(actions), "summary": digest["summary"]}


def enqueue_reopt_plan(client_id: str, trigger: str = "manual") -> None:
    """Enqueue a reopt_plan job (deduped against any in-flight one for the client)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "reopt_plan")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "reopt_plan", "entity_id": client_id, "payload": {"client_id": client_id, "trigger": trigger}}
    ).execute()


async def run_reopt_plan_job(job: dict) -> None:
    """async_jobs handler for job_type='reopt_plan'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    trigger = payload.get("trigger", "scheduled")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = build_plan(client_id, trigger=trigger)
    except Exception as exc:
        # The worker loop only logs unhandled errors; a handler must mark its own
        # job failed (else it sits 'running' until the stale reaper sweeps it).
        logger.warning("reopt_plan_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
