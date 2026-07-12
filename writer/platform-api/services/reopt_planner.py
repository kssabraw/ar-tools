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
from datetime import datetime, timedelta, timezone

from db.supabase_client import get_supabase
from services import notifications, rankability, sop_store

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
_SORT_SITEWIDE = 8 * _TIER   # §A sitewide-decline banner sits above everything
_SORT_DROP = 6 * _TIER
_SORT_OFFPAGE = 5 * _TIER    # aggregate link loss / RD spike: between drops and cannibalization
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
_MAPS_REVIEW_WITHIN = 4_500     # a review-gap action sits just above the GBP-gap action
_MAPS_CONTENT_WITHIN = 3_500    # a content-gap action sits just below the GBP-gap action
_MAPS_RELEVANCE_WITHIN = 5_000  # a local-relevance action sits above review/GBP/content actions
_MAPS_SOLV_WITHIN = 8_500       # a SoLV drop sits near the top of the Maps tier (just under lost_pack)
MAPS_WEAK_AREA_MAX = 5          # cap weak-area actions per plan
SOLV_DROP_MIN_PCT = 10.0        # min Top-3 local-pack share lost (points) to flag a SoLV drop

# Brand-search health (organic). A relative drop in branded impressions, recent
# window vs prior window, signals softening brand demand.
_SORT_BRAND = 1 * _TIER         # hidden-win tier; bumped to the top of it via within
_BRAND_WITHIN = 9_500
_BACKLINK_WITHIN = 9_000        # link-authority gap, just under brand in the hidden tier
_DOMAIN_GAP_WITHIN = 7_000      # competitor keyword-gap opportunities, below backlink in the hidden tier
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

    # 1) Open rank-drop alerts — urgent. When the drop classifier has attached a
    # B1–B5 classification (docs/sops/Rank_Drop_Mitigation_SOP_Organic.md), the
    # action carries that classification's SOP response protocol; unclassified
    # drops keep the generic guidance.
    for d in drops:
        kw = d.get("keyword") or ""
        dropped_keywords.add(kw.lower())
        deindex = d.get("alert_type") == "deindexed"
        response = d.get("response") or {}
        classification = d.get("classification")
        diagnosis = d.get("message") or "Ranking dropped."
        if classification and response.get("label"):
            diagnosis = f"[{classification} — {response['label']}] {diagnosis}"
        actions.append(
            {
                "kind": "rank_drop",
                "source": "organic",
                "keyword": kw,
                "classification": classification,
                "diagnosis": diagnosis,
                "recommendation": response.get("recommendation")
                or (
                    "Confirm indexing — run URL Inspection and check robots/noindex/canonical, then resubmit."
                    if deindex
                    else "Diagnose & reoptimize — capture a SERP snapshot to see what changed (AI Overview, "
                    "a stronger competitor, an intent shift), then reoptimize the ranking page."
                ),
                "cta_label": response.get("cta_label") or "Open rank tracker",
                "cta_path": response.get("cta_path") or f"clients/{client_id}/rankings",
                "severity": "critical" if deindex else "warning",
                "sort": _SORT_DROP + (_SORT_DEINDEX_BONUS if deindex else 0),
                "alert_created_at": d.get("created_at"),
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


def build_offpage_actions(client_id: str, offpage_alerts: list[dict]) -> list[dict]:
    """Map open offpage-agent alerts (RD loss / unnatural spike) to actions per
    the Organic Rank Drop SOP §A.5. Pure (unit-tested)."""
    actions: list[dict] = []
    for a in offpage_alerts:
        alert_type = a.get("alert_type")
        if alert_type == "rd_loss":
            diagnosis = a.get("message") or "Referring domains fell between captures."
            lost = (a.get("details") or {}).get("lost_domains") or []
            if lost:
                diagnosis += " Recently lost referring domains include: " + ", ".join(lost[:8]) + "."
            actions.append(
                {
                    "kind": "rd_loss",
                    "source": "organic",
                    "keyword": "Backlink profile",
                    "diagnosis": diagnosis,
                    "recommendation": "Aggregate link loss (SOP §A.5) — build a replacement plan via the "
                    "Recipe Engine: generate this month's task plan and fund the referring-domains "
                    "variable (the lost RD marks it deficient automatically).",
                    "cta_label": "Action Plan",
                    "cta_path": f"clients/{client_id}/action-plan",
                    "severity": "warning",
                    "sort": _SORT_OFFPAGE + _within(9_000 + abs(a.get("delta_pct") or 0)),
                }
            )
        elif alert_type == "rd_spike":
            actions.append(
                {
                    "kind": "rd_spike",
                    "source": "organic",
                    "keyword": "Backlink profile",
                    "diagnosis": a.get("message") or "Referring domains spiked between captures.",
                    "recommendation": "Unnatural RD spike (SOP §A.5) — check for negative SEO or an "
                    "unintended blast. We never disavow: response levers are anchor dilution, velocity "
                    "throttling, stopping builds, and letting the page settle. MC4 judgment call — "
                    "escalate to the senior SEOs if unclear.",
                    "cta_label": "Action Plan",
                    "cta_path": f"clients/{client_id}/action-plan",
                    "severity": "warning",
                    "sort": _SORT_OFFPAGE + _within(5_000 + abs(a.get("delta_pct") or 0)),
                }
            )
        elif alert_type == "citation_loss":
            dead = (a.get("details") or {}).get("dead_count") or 0
            actions.append(
                {
                    "kind": "citation_loss",
                    "source": "organic",
                    "keyword": "Citations",
                    "diagnosis": a.get("message") or "Citations no longer resolve.",
                    "recommendation": "Dead citations (SOP §A.8 'citations still live') — fix or reorder "
                    "the dead listings. Citations are in the monthly baseline stack ($40/40, Minda); "
                    "replacements are already funded — this is a re-order, not new budget.",
                    "cta_label": "Citations",
                    "cta_path": f"clients/{client_id}/citations",
                    "severity": "warning",
                    "sort": _SORT_OFFPAGE + _within(4_000 + dead * 10),
                }
            )
        elif alert_type == "rd_imbalance":
            actions.append(
                {
                    "kind": "rd_imbalance",
                    "source": "organic",
                    "keyword": "Backlink profile",
                    "diagnosis": a.get("message") or "An inner page carries more RD than the home page.",
                    "recommendation": "Entity-balance hygiene (Link Building SOP health check) — build "
                    "more RD to the home page, or ease off the inner page, until the home page leads "
                    "again. Non-escalating: the SEO NEO assignee self-corrects with rebalanced link "
                    "building.",
                    "cta_label": "Action Plan",
                    "cta_path": f"clients/{client_id}/action-plan",
                    "severity": "info",
                    "sort": _SORT_OFFPAGE + _within(2_000),
                }
            )
    return actions


def build_sitewide_action(client_id: str, scope_info: dict) -> dict:
    """The §A sitewide-decline banner action (Organic Rank Drop SOP): many
    keywords down together means a systemic cause — the per-keyword responses
    below it still apply, but §A's ordered ladder is worked first. Pure."""
    from services.drop_classifier import SITEWIDE_PLAYBOOK, cta_path

    open_drops = scope_info.get("open_drops") or 0
    tracked = scope_info.get("tracked_count") or 0
    return {
        "kind": "sitewide_decline",
        "source": "organic",
        "keyword": "Sitewide",
        "classification": "A",
        "diagnosis": f"[§A — {SITEWIDE_PLAYBOOK['label']}] {open_drops} of {tracked} tracked "
        "keywords have open drops — this pattern points at a systemic cause, not "
        "per-keyword problems.",
        "recommendation": SITEWIDE_PLAYBOOK["recommendation"],
        "cta_label": SITEWIDE_PLAYBOOK["cta_label"],
        "cta_path": cta_path(SITEWIDE_PLAYBOOK["cta_kind"], client_id),
        "severity": "critical",
        "sort": _SORT_SITEWIDE,
    }


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
    comp_n = a.get("competitor_count", 0)
    if score is not None:
        # Only frame the score as competitor-relative when we actually captured
        # competitor profiles to benchmark against — otherwise "vs 0 competitors"
        # reads as a bug. With no competitor data the score is the client's own
        # profile-completeness checks; flag that the benchmark isn't available yet.
        diagnosis = (
            f"GBP completeness {score}/100 vs {comp_n} competitor{'s' if comp_n != 1 else ''}."
            if comp_n
            else f"GBP completeness {score}/100 (profile-completeness only — no competitor "
            "profiles captured yet to benchmark against; run the Maps 'Competitors' fetch)."
        )
    else:
        diagnosis = "GBP has optimization gaps."
    return [
        {
            "kind": "gbp_gap",
            "source": "maps",
            "keyword": "Google Business Profile",
            "diagnosis": diagnosis,
            "recommendation": "Strengthen the Google Business Profile: " + "; ".join(parts) + ".",
            "cta_label": "Open Maps tracker",
            "cta_path": f"clients/{client_id}/maps",
            "severity": "info",
            "sort": _SORT_MAPS + _within(_MAPS_GBP_WITHIN),
        }
    ]


def build_review_action(client_id: str, review_gap: "dict | None") -> list[dict]:
    """A review-growth action when the client's review velocity trails competitors
    or recent negative reviews have landed. Pure."""
    if not review_gap:
        return []
    parts: list[str] = []
    behind = review_gap.get("behind")
    if behind:
        cv = review_gap.get("competitor_velocity")
        parts.append(
            f"review velocity ({review_gap.get('velocity')}/mo) trails competitors"
            + (f" (~{cv}/mo)" if cv is not None else "") + f" by {behind}/mo"
        )
    neg = review_gap.get("recent_negatives") or 0
    if neg:
        parts.append(f"{neg} recent negative review{'s' if neg != 1 else ''}")
    diagnosis = "; ".join(parts).capitalize() + "." if parts else "Review profile needs attention."
    return [
        {
            "kind": "review_gap",
            "source": "maps",
            "keyword": "Reviews",
            "diagnosis": diagnosis,
            "recommendation": "Run a review-generation push (request reviews from recent customers, especially in "
            "weak coverage areas) and respond to negatives to protect rating + local-pack strength.",
            "cta_label": "Open Maps tracker",
            "cta_path": f"clients/{client_id}/maps",
            "severity": "warning" if (review_gap.get("recent_negatives") or 0) else "info",
            "sort": _SORT_MAPS + _within(_MAPS_REVIEW_WITHIN),
        }
    ]


def build_relevance_action(client_id: str, relevance_gap: "dict | None") -> list[dict]:
    """A local-relevance action when the client's GBP/reviews/links don't align
    with the tracked service/location as well as competitors. Pure."""
    if not relevance_gap or not relevance_gap.get("gaps"):
        return []
    kw = relevance_gap.get("keyword")
    return [
        {
            "kind": "local_relevance",
            "source": "maps",
            "keyword": f'"{kw}" relevance' if kw else "Local relevance",
            "diagnosis": "Relevance gaps vs competitors: " + "; ".join(relevance_gap["gaps"][:4]) + ".",
            "recommendation": "Tighten local relevance for this service: point the GBP at a dedicated "
            "service/location page, align the primary category, and encourage reviews that name the service + area.",
            "cta_label": "Open Maps tracker",
            "cta_path": f"clients/{client_id}/maps",
            "severity": "info",
            "sort": _SORT_MAPS + _within(_MAPS_RELEVANCE_WITHIN),
        }
    ]


def build_content_action(client_id: str, content_gap: "dict | None") -> list[dict]:
    """A page-expansion action when the client's page is thinner / misses topics
    competitors cover for a keyword. Pure."""
    if not content_gap:
        return []
    parts: list[str] = []
    depth = content_gap.get("depth_behind")
    if depth:
        parts.append(f"~{int(depth)} words thinner than the competitor median")
    gaps = content_gap.get("topic_gaps") or []
    if gaps:
        parts.append("missing topics: " + ", ".join(gaps[:3]))
    if not parts:
        return []
    kw = content_gap.get("keyword")
    return [
        {
            "kind": "content_gap",
            "source": "maps",
            "keyword": f'"{kw}" page' if kw else "Page content",
            "diagnosis": ("Your page is " + "; ".join(parts) + "."),
            "recommendation": "Expand the page to match the competitors ranking above you — add the missing "
            "sections/topics and depth, keeping it genuinely useful (not padding).",
            "cta_label": "Open Local SEO",
            "cta_path": f"clients/{client_id}/local-seo",
            "severity": "info",
            "sort": _SORT_MAPS + _within(_MAPS_CONTENT_WITHIN),
        }
    ]


def build_backlink_action(client_id: str, backlink_gap: "dict | None") -> list[dict]:
    """A link-building action when the client's domain authority trails the
    local-pack competitor median. Pure. Organic (links help web + local)."""
    if not backlink_gap:
        return []
    parts: list[str] = []
    dr_behind = backlink_gap.get("dr_behind")
    if dr_behind:
        parts.append(f"Domain Rating {dr_behind} behind the competitor median")
    rd_behind = backlink_gap.get("referring_domains_behind")
    if rd_behind:
        parts.append(f"~{int(rd_behind)} fewer referring domains")
    if not parts:
        return []
    return [
        {
            "kind": "backlink_gap",
            "source": "organic",
            "keyword": "Backlink authority",
            "diagnosis": "; ".join(parts) + ".",
            "recommendation": "Run link-building to close the authority gap — local citations/directories, "
            "supplier & partner links, digital PR, and reclaiming unlinked mentions.",
            "cta_label": "Open rank tracker",
            "cta_path": f"clients/{client_id}/rankings",
            "severity": "info",
            "sort": _SORT_HIDDEN + _within(_BACKLINK_WITHIN),
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


def build_domain_intel_actions(client_id: str, gaps: list[dict]) -> list[dict]:
    """Top competitor keyword-gap opportunities (Domain Intelligence) as Action
    Plan items — keywords a competitor ranks for that the client doesn't. Pure.

    ``gaps`` is opportunity-sorted domain_keyword_gaps rows; the top N surface as
    'create/strengthen a page' actions deep-linking into Domain Intelligence."""
    from config import settings

    actions: list[dict] = []
    for i, g in enumerate(gaps[: settings.domain_intel_action_max]):
        kw = g.get("keyword")
        if not kw:
            continue
        comp = g.get("competitor_domain") or "a competitor"
        comp_pos = g.get("competitor_position")
        cli_pos = g.get("client_position")
        where = "you don't rank" if cli_pos is None else f"you rank #{cli_pos}"
        vol = g.get("volume")
        vol_txt = f" ~{vol}/mo searches." if vol else ""
        actions.append(
            {
                "kind": "keyword_gap",
                "source": "organic",
                "keyword": kw,
                "diagnosis": f"{comp} ranks"
                + (f" #{comp_pos}" if comp_pos else "")
                + f" for this; {where}.{vol_txt}",
                "recommendation": "Competitive keyword gap — create or strengthen a page targeting this "
                "term. Review the full ranked gap list (with backlink gaps and competitor discovery) "
                "in Domain Intelligence.",
                "cta_label": "Domain Intelligence",
                "cta_path": f"clients/{client_id}/domain-intel",
                "severity": "info",
                "sort": _SORT_HIDDEN + _within(_DOMAIN_GAP_WITHIN - i),
            }
        )
    return actions


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
        + by_kind.get("review_gap", 0)
        + by_kind.get("content_gap", 0)
        + by_kind.get("local_relevance", 0)
    )
    if maps:
        parts.append(f"{maps} local-pack issue{'s' if maps != 1 else ''}")
    other = (
        by_kind.get("cannibalization", 0)
        + by_kind.get("opportunity", 0)
        + by_kind.get("brand_search_decline", 0)
        + by_kind.get("backlink_gap", 0)
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


def _fetch_relevance_gap(supabase, client_id: str) -> "dict | None":
    """Best-effort local-relevance gap signal from the latest stored scorecard."""
    try:
        from services import local_relevance

        scorecard = local_relevance.latest_scorecard(client_id)
        if not scorecard.get("client"):
            return None
        return local_relevance.detect_relevance_gaps(scorecard)
    except Exception as exc:
        logger.warning("reopt_plan_relevance_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _fetch_content_gap(supabase, client_id: str) -> "dict | None":
    """Best-effort content-gap signal from the latest stored website analysis."""
    try:
        from config import settings
        from services import content_intel

        analyses = content_intel.latest_analyses(client_id)
        if not analyses:
            return None
        a = analyses[0]  # most recent keyword analysis
        comparison = {
            "depth_behind": a.get("depth_behind"),
            "topic_gaps": a.get("topic_gaps") or [],
            "keyword": a.get("keyword"),
        }
        return content_intel.detect_content_gap(
            comparison, settings.content_depth_behind_min, settings.content_topic_gap_min
        )
    except Exception as exc:
        logger.warning("reopt_plan_content_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _fetch_review_gap(supabase, client_id: str) -> "dict | None":
    """Best-effort review-velocity/negatives signal from stored review analytics."""
    try:
        from config import settings
        from services import review_analytics

        intel = review_analytics.get_review_intel(client_id)
        if not intel["competitors"]:
            return None
        return review_analytics.detect_review_gap(
            intel["comparison"], intel["client"], settings.review_gap_min_behind
        )
    except Exception as exc:
        logger.warning("reopt_plan_review_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _fetch_backlink_gap(supabase, client_id: str) -> "dict | None":
    """Best-effort backlink-authority gap signal from stored backlink profiles."""
    try:
        from config import settings
        from services import backlink_intel

        intel = backlink_intel.get_backlink_intel(client_id)
        if not intel["competitors"] or not intel["client"]:
            return None
        return backlink_intel.detect_backlink_gap(
            intel["comparison"], settings.backlink_dr_min_behind, settings.backlink_rd_min_behind
        )
    except Exception as exc:
        logger.warning("reopt_plan_backlink_failed", extra={"client_id": client_id, "error": str(exc)})
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


def _is_stale(supabase, table: str, client_id: str, days: int) -> bool:
    """Whether the latest `captured_at` for a client in `table` is missing or older
    than `days`. Used to interval-gate the paid intel refreshes."""
    try:
        rows = (
            supabase.table(table).select("captured_at")
            .eq("client_id", client_id).order("captured_at", desc=True).limit(1).execute()
        ).data or []
    except Exception:
        return False  # can't tell → don't churn paid jobs
    if not rows or not rows[0].get("captured_at"):
        return True
    try:
        captured = datetime.fromisoformat(str(rows[0]["captured_at"]).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return captured < datetime.now(timezone.utc) - timedelta(days=days)


def _maybe_refresh_intel(supabase, client_id: str) -> None:
    """Best-effort: when building a plan, top up the competitor-GBP + backlink
    intelligence that the GBP benchmark and backlink-gap action depend on, so they
    stop reading as empty. Interval-gated (paid API calls) and dedupe-guarded by
    each enqueue. Backlink intel needs competitor GBP profiles first (it derives
    competitor domains from them), so it's only enqueued once those exist — on a
    fresh client they populate this cycle and backlink intel follows next cycle.
    The data refreshed here lands on the *next* rebuild; this run uses what's
    stored. Never raises."""
    from config import settings

    if not settings.reopt_auto_intel:
        return
    days = settings.reopt_intel_refresh_days
    try:
        from services import backlink_intel, competitor_gbp

        # Competitor GBP needs a completed Maps scan to know who the competitors are.
        has_scan = bool(
            (supabase.table("maps_scans").select("id")
             .eq("client_id", client_id).eq("status", "complete").limit(1).execute()).data
        )
        has_competitor_profiles = bool(competitor_gbp.latest_profiles(client_id))

        if has_scan and _is_stale(supabase, "competitor_gbp_profiles", client_id, days):
            competitor_gbp.enqueue_competitor_gbp(client_id)
        # Only chase backlinks once we have competitor domains to compare against.
        if has_competitor_profiles and _is_stale(supabase, "backlink_profiles", client_id, days):
            backlink_intel.enqueue_backlink_intel(client_id)
    except Exception as exc:
        logger.warning("reopt_auto_intel_failed", extra={"client_id": client_id, "error": str(exc)})


def build_plan(client_id: str, trigger: str = "manual") -> dict:
    """Gather signals, build the ranked plan, store it, and (on the weekly
    cadence) push a digest notification. Returns the stored plan summary."""
    supabase = get_supabase()

    # Top up the paid competitor-GBP + backlink intel (interval-gated); results
    # land on the next rebuild. Best-effort — never blocks the plan.
    _maybe_refresh_intel(supabase, client_id)

    drops = (
        supabase.table("rank_alerts")
        .select("keyword_id, keyword, alert_type, message, created_at")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []

    # Classify each open drop per the Organic Rank Drop SOP (B1–B5 + scope) so
    # the actions carry the SOP's response protocols. Best-effort — an
    # unclassified drop keeps the generic guidance.
    scope_info: dict = {}
    try:
        from services import drop_classifier

        scope_info = drop_classifier.classify_client_drops(client_id, drops)
    except Exception as exc:
        logger.warning("reopt_plan_classify_failed", extra={"client_id": client_id, "error": str(exc)})

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
    review_gap = _fetch_review_gap(supabase, client_id)
    backlink_gap = _fetch_backlink_gap(supabase, client_id)
    content_gap = _fetch_content_gap(supabase, client_id)
    relevance_gap = _fetch_relevance_gap(supabase, client_id)

    # Build organic uncapped so Maps actions compete fairly for the combined cap.
    organic = build_actions(client_id, drops, rankability_items, gsc, cap=None)
    if scope_info.get("sitewide"):
        organic.insert(0, build_sitewide_action(client_id, scope_info))
    # Offpage-agent alerts (aggregate RD loss / unnatural spike — SOP §A.5).
    try:
        from services.offpage_agent import open_offpage_alerts

        organic += build_offpage_actions(client_id, open_offpage_alerts(client_id))
    except Exception as exc:
        logger.warning("reopt_plan_offpage_failed", extra={"client_id": client_id, "error": str(exc)})
    # Competitive keyword-gap opportunities (Domain Intelligence). Additive:
    # no stored gaps → no actions → unchanged behavior.
    try:
        gap_rows = (
            supabase.table("domain_keyword_gaps")
            .select("keyword, competitor_domain, competitor_position, client_position, volume, opportunity_score")
            .eq("client_id", client_id)
            .order("opportunity_score", desc=True)
            .limit(settings.domain_intel_action_max)
            .execute()
        ).data or []
        organic += build_domain_intel_actions(client_id, gap_rows)
    except Exception as exc:
        logger.warning("reopt_plan_domain_intel_failed", extra={"client_id": client_id, "error": str(exc)})
    maps_actions = build_maps_actions(client_id, maps_alerts, weak_areas, solv_drop)
    maps_actions += build_relevance_action(client_id, relevance_gap)
    maps_actions += build_gbp_action(client_id, gbp_audit_result)
    maps_actions += build_review_action(client_id, review_gap)
    maps_actions += build_content_action(client_id, content_gap)
    brand_actions = build_brand_action(client_id, brand_decline)
    brand_actions += build_backlink_action(client_id, backlink_gap)
    actions = organic + maps_actions + brand_actions
    actions.sort(key=lambda a: a["sort"], reverse=True)
    actions = actions[:TOTAL_MAX]

    # Verify-loop notes: append each open response episode's clock (2-week
    # recheck / 6-week escalation state) to its keyword's action rows —
    # organic and maps alike. Best-effort.
    try:
        from services.response_episodes import open_episode_notes

        notes = open_episode_notes(client_id)
        if notes:
            for a in actions:
                note = notes.get((a.get("keyword") or "").lower())
                if note:
                    a["episode_note"] = note
                    a["diagnosis"] = f"{a['diagnosis']} {note}"
    except Exception as exc:
        logger.warning("reopt_plan_episode_notes_failed", extra={"client_id": client_id, "error": str(exc)})

    # Algo-update context: a drop that opened while several clients dropped
    # together is a Google update, not this client's emergency — annotate so
    # nobody reoptimizes into a rolling update (Organic SOP §A). Best-effort.
    try:
        from services.trend_watch import algo_note_for, recent_algo_events

        events = recent_algo_events()
        if events:
            for a in actions:
                if a.get("kind") != "rank_drop":
                    continue
                note = algo_note_for(a.get("alert_created_at"), events)
                if note:
                    a["algo_note"] = note
                    a["diagnosis"] = f"{a['diagnosis']} {note}"
    except Exception as exc:
        logger.warning("reopt_plan_algo_notes_failed", extra={"client_id": client_id, "error": str(exc)})
    digest = summarize_plan(actions)

    latest = (
        supabase.table("reopt_plans")
        .select("id, action_count, items")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    latest_count = latest[0]["action_count"] if latest else None
    # Sitewide-decline TRANSITION detection for the strategist escalation brief:
    # fire only when this build turns sitewide on and the previous plan wasn't —
    # a client sitting in a sitewide state doesn't re-brief on every rebuild.
    prev_had_sitewide = bool(latest) and any(
        a.get("kind") == "sitewide_decline" for a in (latest[0].get("items") or [])
    )

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

    # Native task manager producer (PRD §11): mirror the plan's top actions
    # into tasks (create new, auto-close departed). Self-gated + best-effort.
    from services import task_producers

    task_producers.sync_action_plan_tasks(client_id, actions)

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

    # SerMaStr escalation brief (Phase 4): a §A sitewide decline just opened —
    # a systemic cause needs a strategic read, not per-keyword fixes. The
    # enqueue no-ops while strategist_enabled is false; best-effort.
    if scope_info.get("sitewide") and not prev_had_sitewide:
        try:
            from services.strategist import enqueue_strategy_review

            enqueue_strategy_review(
                client_id,
                trigger="escalation",
                escalation_context={
                    "kind": "sitewide_decline",
                    "open_drops": scope_info.get("open_drops"),
                    "tracked_count": scope_info.get("tracked_count"),
                    "plan_id": plan["id"],
                },
            )
        except Exception as exc:
            logger.warning(
                "reopt_plan_sitewide_brief_failed",
                extra={"client_id": client_id, "error": str(exc)},
            )

    logger.info(
        "reopt_plan_built",
        extra={"client_id": client_id, "trigger": trigger, "actions": len(actions)},
    )
    return {"plan_id": plan["id"], "action_count": len(actions), "summary": digest["summary"]}


# ----------------------------------------------------------------------------
# SOP-grounded enrichment — rewrites each action's guidance in the agency's own
# methodology + voice, using the SOP store (agency-wide + per-client) and the
# client's existing context. One Claude call per plan; best-effort; skipped when
# no SOPs exist so it stays free until a playbook is loaded.
# ----------------------------------------------------------------------------
_ENRICH_TOOL = {
    "name": "emit_details",
    "description": "Emit the SOP-grounded detail for each action, keyed by its index.",
    "input_schema": {
        "type": "object",
        "properties": {
            "details": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The action's index from the input list."},
                        "why": {"type": "string", "description": "Why this matters for THIS client, grounded in the SOPs."},
                        "steps": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Concrete, ordered steps to execute per the agency's SOPs.",
                        },
                        "sop_refs": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Titles of the SOPs/theories this draws on (empty if none applied).",
                        },
                    },
                    "required": ["index", "why", "steps"],
                },
            },
        },
        "required": ["details"],
    },
}

_ENRICH_SYSTEM = (
    "You are a senior SEO strategist at an agency. You turn a terse, "
    "auto-generated reoptimization action into a detailed, client-specific plan "
    "that follows the agency's own SOPs and strategic theories. Use ONLY the "
    "agency's methodology provided; do not invent steps that contradict it. Be "
    "concrete and practical. If no SOP is relevant to an action, still give sound, "
    "specific steps but leave sop_refs empty. Never fabricate SOP titles."
)


def _client_context_for_enrich(client: dict) -> str:
    """Compact client context block for the enrichment prompt."""
    from services import icp_service

    gbp = client.get("gbp") or {}
    lines = [f"Business: {client.get('name') or '—'}"]
    cat = gbp.get("gbp_category")
    if cat:
        lines.append(f"Primary category: {cat}")
    addr = gbp.get("address")
    if addr:
        lines.append(f"Location: {addr}")
    icp = icp_service.resolve_icp_text(client)
    if icp:
        lines.append("\nIdeal customer / differentiators:\n" + icp[:4000])
    return "\n".join(lines)


def _build_enrich_prompt(client_ctx: str, sops_text: str, actions: list[dict]) -> str:
    import json

    compact = [
        {
            "index": i,
            "type": a.get("kind"),
            "channel": a.get("source"),
            "target": a.get("keyword"),
            "diagnosis": a.get("diagnosis"),
            "current_recommendation": a.get("recommendation"),
        }
        for i, a in enumerate(actions)
    ]
    return (
        f"CLIENT CONTEXT:\n{client_ctx}\n\n"
        f"AGENCY SOPs & THEORIES (ground every step in these):\n{sops_text}\n\n"
        f"ACTIONS TO DETAIL (return one details entry per index):\n"
        f"{json.dumps(compact, indent=2, default=str)}\n\n"
        "For each action, return: why it matters for THIS client (grounded in the "
        "SOPs), the concrete ordered steps to execute it per the agency's "
        "methodology, and which SOP/theory titles you drew on."
    )


async def _call_enrich_llm(client_ctx: str, sops_text: str, actions: list[dict]) -> dict:
    """One forced-tool Claude call → {index: {why, steps, sop_refs}}."""
    import anthropic

    from config import settings

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.reopt_enrich_model,
        max_tokens=settings.reopt_enrich_max_tokens,
        system=_ENRICH_SYSTEM,
        tools=[_ENRICH_TOOL],
        tool_choice={"type": "tool", "name": "emit_details"},
        messages=[{"role": "user", "content": _build_enrich_prompt(client_ctx, sops_text, actions)}],
    )
    out = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_details":
            out = block.input or {}
            break
    if out is None:
        raise RuntimeError(f"reopt_enrich_no_tool_use (stop={response.stop_reason})")
    by_index: dict[int, dict] = {}
    for d in out.get("details") or []:
        idx = d.get("index")
        if isinstance(idx, int):
            by_index[idx] = {
                "why": (d.get("why") or "").strip(),
                "steps": [s for s in (d.get("steps") or []) if s and s.strip()],
                "sop_refs": [s for s in (d.get("sop_refs") or []) if s and s.strip()],
            }
    return by_index


async def enrich_plan(client_id: str, plan_id: "str | None" = None) -> bool:
    """Rewrite a stored plan's actions with SOP-grounded detail. Best-effort:
    returns False (leaving the deterministic plan untouched) when there are no
    SOPs, no actions, or the LLM call fails. Returns True when detail was applied."""
    supabase = get_supabase()
    sops_text = sop_store.resolve_sops_text(client_id)
    if not sops_text:
        return False  # nothing to ground on — keep the static guide, no LLM cost

    if plan_id:
        rows = supabase.table("reopt_plans").select("id, items").eq("id", plan_id).limit(1).execute().data
    else:
        rows = (
            supabase.table("reopt_plans").select("id, items")
            .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()
        ).data
    if not rows:
        return False
    plan = rows[0]
    actions = plan.get("items") or []
    if not actions:
        return False

    try:
        client = (
            supabase.table("clients")
            .select("name, gbp, detected_icp, differentiators, icp_text")
            .eq("id", client_id).limit(1).execute()
        ).data
        client_ctx = _client_context_for_enrich(client[0]) if client else f"Business id {client_id}"
        by_index = await _call_enrich_llm(client_ctx, sops_text, actions)
    except Exception as exc:
        logger.warning("reopt_enrich_failed", extra={"client_id": client_id, "error": str(exc)})
        return False

    if not by_index:
        return False
    for i, a in enumerate(actions):
        detail = by_index.get(i)
        if detail and (detail["why"] or detail["steps"]):
            a["detail"] = detail
    try:
        supabase.table("reopt_plans").update({"items": actions}).eq("id", plan["id"]).execute()
    except Exception as exc:
        logger.warning("reopt_enrich_store_failed", extra={"client_id": client_id, "error": str(exc)})
        return False
    logger.info("reopt_plan_enriched", extra={"client_id": client_id, "enriched": len(by_index)})
    return True


def enqueue_reopt_plan(client_id: str, trigger: str = "manual") -> None:
    """Enqueue a reopt_plan job, deduped so a client's action plan isn't rebuilt
    many times a day.

    Cadence (owner decision — strictly weekly + manual):

    0. Event-trigger gate: ``drop``/``maps_drop``/``offpage`` rebuilds are
       suppressed unless ``reopt_plan_event_refresh_enabled`` is set. The drop
       still surfaces via the alert/notifications path; the plan just folds it in
       on the next weekly run or a manual refresh. ``manual`` and ``scheduled``
       are never gated here.

    Then two guards, both skipped for a user-initiated ``manual`` refresh (that
    always runs):

    1. In-flight dedup (all triggers): never stack a second job while one is
       already pending/running for the client.
    2. Recency debounce (automated triggers): the scheduler's weekly day-gate is
       held in an in-memory variable, so every platform-api restart on the weekly
       day re-fires the ``scheduled`` pass — producing several identical rebuilds
       in one day. So a ``scheduled`` rebuild is collapsed to at most one per UTC
       day (which, given the weekday gate, is effectively once per week). When
       event refreshes are re-enabled, an event-driven rebuild is likewise skipped
       when a plan already completed within ``reopt_plan_min_interval_hours``.
    """
    from config import settings

    if trigger not in ("manual", "scheduled") and not settings.reopt_plan_event_refresh_enabled:
        logger.info(
            "reopt_plan_event_refresh_disabled",
            extra={"client_id": client_id, "trigger": trigger},
        )
        return

    supabase = get_supabase()
    in_flight = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "reopt_plan")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if in_flight.data:
        return

    if trigger != "manual":
        now = datetime.now(timezone.utc)
        if trigger == "scheduled":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = now - timedelta(hours=max(0, settings.reopt_plan_min_interval_hours))
        if cutoff < now:
            recent = (
                supabase.table("async_jobs")
                .select("id")
                .eq("job_type", "reopt_plan")
                .eq("entity_id", client_id)
                .eq("status", "complete")
                .gte("created_at", cutoff.isoformat())
                .limit(1)
                .execute()
            )
            if recent.data:
                logger.info(
                    "reopt_plan_debounced",
                    extra={"client_id": client_id, "trigger": trigger},
                )
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

    # SOP-grounded enrichment (best-effort; no-op when no SOPs exist).
    try:
        await enrich_plan(client_id, plan_id=result.get("plan_id"))
    except Exception as exc:  # never fail the job over enrichment
        logger.warning("reopt_enrich_job_failed", extra={"client_id": client_id, "error": str(exc)})
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()
