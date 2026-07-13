"""LeadOff — market-intelligence service (Module: docs/modules/leadoff-prd-v1_0.md).

Serves the precomputed market board (market_scanner.leadoff_board — 34k city x
category markets scored by the LeadOff scanner) and a per-market brief (top-5
competitors + any cached Pass-2 enrichment). Read-only in v1: no paid API calls.

Stored board numbers assume capture=0.10 and lead tier "mid"; other assumptions
are recomputed here from the row's assumption-independent components
(xdem, rankab, rev_win) + the per-category lead-value table. The national
percentile reference (exp_val_percentiles) is fixed at the default assumptions,
so grades under non-default assumptions are approximate — same behavior as the
source PowerShell tool. Agent usage rules: docs/sops/LeadOff_Market_Intelligence_SOP.md.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from typing import Any

DEFAULT_CAPTURE = 0.10
DEFAULT_TIER = "mid"
LEAD_TIERS = ("low", "mid", "high")
BOARD_SORTS = ("build", "roi", "expected", "value", "leads", "demand", "v3")

# pre-rank column used to bound the fetch before exact re-sort in Python
_PRERANK_COLUMN = {
    "build": "build", "roi": "roi", "expected": "exp_val", "value": "value_mo",
    "leads": "xdem", "demand": "xdem", "v3": "v3",
}
_GRADE_BANDS = [(99, "A+"), (97, "A"), (94, "B+"), (90, "B"), (75, "C"), (50, "D")]
# The shared review cache is cross-category, so a market's top-5 often only
# partly matches it. A momentum verdict from a single business over-reads —
# require at least this many matched competitors before calling one.
MOMENTUM_MIN_MATCHED = 2


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()


# ── Pure logic (unit-tested in tests/test_leadoff.py) ─────────────────────────

def percentile_of(exp_val: float, breakpoints: list[float]) -> float:
    """National percentile (0-100) of an expected value against the sorted
    101-point reference (index i == the i-th percentile's threshold)."""
    if not breakpoints:
        return 0.0
    pos = bisect_right(breakpoints, exp_val)
    return round(min(100.0, pos * 100.0 / len(breakpoints)), 1)


def grade_for(pct: float, leads_mo: float, rankab: float,
              lead_value: float | None) -> tuple[str, float]:
    """Build grade with the LeadOff vetoes: too-small or too-hard markets are
    capped at C; no lead value is an F. Returns (grade, capped build score)."""
    if lead_value is None:
        return "F", 0.0
    score = pct
    if leads_mo < 5 or rankab < 0.15:
        score = min(score, 74.9)
    for cut, grade in _GRADE_BANDS:
        if score >= cut:
            return grade, score
    return "F", score


def recompute_economics(row: dict[str, Any], capture: float, lead_value: float | None,
                        breakpoints: list[float]) -> dict[str, Any]:
    """Re-derive the assumption-dependent numbers from a stored board row.

    Assumption-independent inputs: xdem (regressed demand), rankab
    (win-likelihood), rev_win (reviews to beat #3). Everything else follows:
    leads = xdem x capture; value = leads x lead_value; exp_val = value x rankab;
    roi = exp_val / max(rev_win, 10).
    """
    xdem = float(row.get("xdem") or 0)
    rankab = float(row.get("rankab") or 0)
    rev_win = float(row.get("rev_win") or 0)
    leads = xdem * capture
    value = leads * lead_value if lead_value is not None else None
    exp_val = round(value * rankab) if value is not None else 0
    grade, build = grade_for(percentile_of(exp_val, breakpoints), leads, rankab,
                             lead_value)
    return {
        **row,
        "est_leads_mo": round(leads),
        "exp_leads_mo": round(leads * rankab),
        "value_mo": round(value) if value is not None else None,
        "exp_val": exp_val,
        "roi": round(exp_val / max(rev_win, 10), 1),
        "grade": grade,
        "build": build,
    }


def sort_value(row: dict[str, Any], sort: str) -> float:
    key = {"build": "build", "roi": "roi", "expected": "exp_val",
           "value": "value_mo", "leads": "exp_leads_mo", "demand": "xdem",
           "v3": "v3"}[sort]
    v = row.get(key)
    return float(v) if v is not None else -1.0


def enrichment_from_caches(competitors: list[dict[str, Any]],
                           rd_rows: list[dict[str, Any]],
                           review_rows: list[dict[str, Any]],
                           trend_row: dict[str, Any] | None,
                           city_id: int) -> dict[str, Any] | None:
    """Assemble the Pass-2 enrichment block from whatever the shared caches
    hold (best-effort; None when nothing is cached for this market). RD values
    are tool reads — display converts x10 to true RD per _ORCHESTRATOR.md §2."""
    rd_by_domain = {r["domain"]: r.get("referring_domains") for r in rd_rows}
    rds = [rd_by_domain[c["domain"]] for c in competitors
           if c.get("domain") and rd_by_domain.get(c["domain"]) is not None]
    vel_by_key = {r["biz_key"]: r for r in review_rows}
    last30 = prior30 = 0
    newest: list[str] = []
    matched = 0
    for c in competitors:
        v = vel_by_key.get(f"{_norm(c.get('business_name') or '')}|{city_id}")
        if v:
            matched += 1
            last30 += int(v.get("last30") or 0)
            prior30 += int(v.get("prior30") or 0)
            if v.get("newest"):
                newest.append(str(v["newest"]))
    if not rds and not matched and not trend_row:
        return None
    momentum = None
    if matched >= MOMENTUM_MIN_MATCHED:
        momentum = ("accel" if last30 > prior30 * 1.3
                    else "cooling" if last30 < prior30 * 0.7 else "steady") \
            if (last30 or prior30) else "dead"
    return {
        "rd_min": min(rds) if rds else None,
        "rd_med": sorted(rds)[len(rds) // 2] if rds else None,
        "field_vel30": last30 if matched else None,
        "field_prior30": prior30 if matched else None,
        "vel_matched": matched if matched else None,
        "momentum": momentum,
        "newest_review": max(newest) if newest else None,
        "growth_yoy": (trend_row or {}).get("growth_yoy"),
        # same-month YoY (seasonality-cancelling; null on pre-24mo rows)
        "growth_yoy_ss": (trend_row or {}).get("growth_yoy_ss"),
        "peak_months": (trend_row or {}).get("peak_months"),
    }


def handoff_competitors(competitors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """client_competitors seed rows from a market's top-5. serp_top5 carries no
    place_id, so identity is the (scanner-normalized) domain — or name-only for
    competitors without sites. Deduped by domain to respect the registry's
    partial-unique index."""
    rows: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for c in competitors:
        name = str(c.get("business_name") or "").strip()
        if not name:
            continue
        domain = (str(c.get("domain") or "")).strip().lower() or None
        if domain:
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
        bits = [f"LeadOff top-5 #{c.get('rank_position')}"]
        if c.get("review_count") is not None:
            bits.append(f"{c['review_count']} reviews")
        if c.get("rating") is not None:
            bits.append(f"{c['rating']}★")
        rows.append({"name": name, "domain": domain,
                     "sources": ["leadoff"], "notes": " · ".join(bits)})
    return rows


def handoff_goal(row: dict[str, Any],
                 enrichment: dict[str, Any] | None,
                 proximity: dict[str, Any] | None = None) -> dict[str, Any]:
    """Custom campaign-goal fields carrying the market's effort targets, so the
    strategist judges the campaign against what LeadOff said it would take.
    Manual goal (no auto-measurement): the targets are entry-decision numbers,
    re-verified against live scans once the campaign runs."""
    city = f"{row.get('city_name')}, {row.get('state_code')}"
    lines = [
        (f"LeadOff {row.get('as_of')} · grade {row.get('grade')} · expected "
         f"${row.get('exp_val')}/mo (capture 10%, mid lead value)."),
        (f"Review target: ~{row.get('rev_win')} reviews to beat the #3 "
         f"incumbent (add margin; recheck against a live scan)."),
    ]
    if enrichment:
        if enrichment.get("rd_min") is not None:
            lines.append(
                f"Link budget: ~{int(enrichment['rd_min']) * 10} true RD to "
                f"match the weakest top-5 site (tool read ×10 per the LeadOff SOP §5).")
        if enrichment.get("momentum"):
            lines.append(
                f"Field momentum at scan: {enrichment['momentum']} (field reviews "
                f"30d {enrichment.get('field_vel30')} vs {enrichment.get('field_prior30')}).")
    # Distance-pillar placement (proximity plan §3): the suggested GBP zone(s)
    # where no ranked competitor is anchored — a concrete entry recommendation.
    if proximity and proximity.get("available") and proximity.get("placement"):
        def _zone(p: dict[str, Any]) -> str:
            loc = p.get("locality")
            return f"{p.get('octant')}" + (f" (near {loc})" if loc else "")
        zones = ", ".join(_zone(p) for p in proximity["placement"])
        lines.append(
            f"Suggested GBP placement: {zones} — undefended by ranked "
            f"competitors (pre-client proximity read; the geo-grid verifies "
            f"post-client).")
    return {
        "goal_type": "custom",
        "label": f"LeadOff targets — {row.get('category')} in {city}",
        "target_value": None,
        "notes": "\n".join(lines),
    }


# ── Data access (market_scanner via the scoped client) ────────────────────────

def _client():
    from services.leadoff_db import get_leadoff_client
    return get_leadoff_client()


def _lead_values(tier: str) -> dict[str, float]:
    col = {"low": "cpl_low", "mid": "cpl_mid", "high": "cpl_high"}[tier]
    rows = (_client().table("lead_values")
            .select(f"category_name,{col}").execute().data or [])
    return {r["category_name"]: r[col] for r in rows if r.get(col) is not None}


def _percentile_breakpoints() -> list[float]:
    rows = (_client().table("exp_val_percentiles")
            .select("pct,exp_val").order("pct").execute().data or [])
    return [float(r["exp_val"]) for r in rows]


def attach_permits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the app-owned prospect-pipeline columns (public.city_permits,
    written by the leadoff_permits job) onto board/brief rows at read time —
    the board table itself is scanner-owned and reload-wiped, so permits
    live outside it. Adds permit_relevance per row (display prominence only,
    plan §4). Best-effort: no permits store → rows unchanged."""
    if not rows:
        return rows
    try:
        from db.supabase_client import get_supabase
        from services.leadoff_permits import permit_relevance

        ids = sorted({r["city_id"] for r in rows if r.get("city_id") is not None})
        permits = {p["city_id"]: p for p in (
            get_supabase().table("city_permits")
            .select("city_id,permit_units_1yr,permits_pc,permit_sf_share,"
                    "permit_trend,permit_flag,permit_source,vintage")
            .in_("city_id", ids).execute().data or [])}
        for r in rows:
            p = permits.get(r.get("city_id"))
            if p and p.get("permit_source") == "place":
                r.update({k: p.get(k) for k in (
                    "permit_units_1yr", "permits_pc", "permit_sf_share",
                    "permit_trend", "permit_flag")})
                r["permit_vintage"] = p.get("vintage")
            r["permit_relevance"] = permit_relevance(r.get("category") or "")
    except Exception:
        # the pipeline column is context — never break the board over it
        import logging
        logging.getLogger(__name__).warning("leadoff.attach_permits_failed",
                                            exc_info=True)
    return rows


def list_board(*, city: str | None, state: str | None, category: str | None,
               min_demand: int | None, sort: str, capture: float, lead_tier: str,
               limit: int, prefetch: int) -> dict[str, Any]:
    q = _client().table("leadoff_board").select("*")
    if city:
        q = q.ilike("city_name", f"%{city}%")
    if state:
        q = q.eq("state_code", state.upper())
    if category:
        q = q.ilike("category", f"%{category}%")
    if min_demand:
        q = q.gte("xdem", min_demand)
    prerank = _PRERANK_COLUMN[sort]
    rows = (q.order(prerank, desc=True)
            .limit(max(limit, prefetch)).execute().data or [])

    default_assumptions = (abs(capture - DEFAULT_CAPTURE) < 1e-9
                           and lead_tier == DEFAULT_TIER)
    if not default_assumptions:
        lv = _lead_values(lead_tier)
        bp = _percentile_breakpoints()
        rows = [recompute_economics(r, capture, lv.get(r.get("category")), bp)
                for r in rows]
    rows.sort(key=lambda r: sort_value(r, sort) if not default_assumptions
              else float(r.get(prerank) or -1), reverse=True)
    as_of = rows[0].get("as_of") if rows else None
    markets = attach_permits(rows[:limit])
    markets = _enrich_board_grades(markets, capture, lead_tier, sort)
    return {"markets": markets, "as_of": as_of,
            "assumptions": {"capture": capture, "lead_tier": lead_tier,
                            "approximate": not default_assumptions}}


def _enrich_board_grades(markets: list[dict[str, Any]], capture: float,
                         lead_tier: str, sort: str) -> list[dict[str, Any]]:
    """Board-wide grade enrichment (owner ruling 2026-07-12). Demand-side
    **permit** signal from the joined permit_flag ($0, always) + the winnability
    signals (**proximity**, incumbent **site/brand** pressure) read from the
    precomputed public.leadoff_market_signals cache (increment 2 — populated by
    the leadoff_signal_refresh job so octant math isn't recomputed per row).
    Markets the cache hasn't reached yet degrade to permit-only. Re-sorts the
    displayed set on the enriched score so ordering matches the shown grades."""
    from config import settings
    if not settings.leadoff_scoring_enabled or not markets:
        return markets
    try:
        from db.supabase_client import get_supabase
        from services import leadoff_scoring
        from services.leadoff_signals import read_signals

        cached = read_signals(get_supabase(),
                              [(r.get("city_id"), r.get("category_id"))
                               for r in markets])
        lv = _lead_values(lead_tier)
        bp = _percentile_breakpoints()
        w = leadoff_scoring.default_weights()
        out = []
        for r in markets:
            c = cached.get((r.get("city_id"), r.get("category_id"))) or {}
            signals = {
                "permit": (leadoff_scoring.permit_signal(r.get("permit_flag"))
                           if r.get("permit_flag") else None),
                "proximity": c.get("proximity_opportunity"),
                "site_pressure": c.get("site_pressure"),
                "brand_pressure": c.get("brand_pressure"),
            }
            out.append(leadoff_scoring.enrich_grade(
                r, signals, capture=capture, lead_value=lv.get(r.get("category")),
                breakpoints=bp, w=w))
        out.sort(key=lambda r: sort_value(r, sort), reverse=True)
        return out
    except Exception:
        import logging
        logging.getLogger(__name__).warning("leadoff.board_enrich_failed",
                                            exc_info=True)
        return markets


NEIGHBORHOOD_SORTS = {
    "demand": "demand_vol", "value": "est_value_mo",
    "leads": "est_leads_mo", "v3": "opportunity_score_v3",
}


def list_neighborhoods(*, metro: str | None, state: str | None,
                       service: str | None, sort: str, limit: int) -> dict[str, Any]:
    """The nameable-neighborhood board (PRD §5 item 3): 955 combos precomputed
    by the scanner. Scored on demand/economics, NOT competition — neighborhood
    supply ≈ the parent metro's at 13z (scanner lesson #5), so competition
    columns are context, not signal."""
    q = _client().table("neighborhood_opportunities").select("*")
    if metro:
        q = q.ilike("metro", f"%{metro}%")
    if state:
        q = q.eq("state", state.upper())
    if service:
        q = q.ilike("service", f"%{service}%")
    rows = (q.order(NEIGHBORHOOD_SORTS[sort], desc=True, nullsfirst=False)
            .limit(limit).execute().data or [])
    return {"neighborhoods": rows}


def get_market_brief(city_id: int, category_id: str) -> dict[str, Any] | None:
    board = (_client().table("leadoff_board").select("*")
             .eq("city_id", city_id).eq("category_id", category_id)
             .limit(1).execute().data or [])
    if not board:
        return None
    row = board[0]
    comps = (_client().table("serp_top5")
             .select("rank_position,business_name,rating,review_count,domain")
             .eq("city_id", city_id).eq("category_id", category_id)
             .order("rank_position").limit(5).execute().data or [])
    domains = [c["domain"] for c in comps if c.get("domain")]
    rd_rows = ((_client().table("domain_backlinks")
                .select("domain,referring_domains").in_("domain", domains)
                .execute().data or []) if domains else [])
    keys = [f"{_norm(c.get('business_name') or '')}|{city_id}" for c in comps]
    review_rows = ((_client().table("business_reviews")
                    .select("biz_key,last30,prior30,newest").in_("biz_key", keys)
                    .execute().data or []) if keys else [])
    trend = (_client().table("demand_trend")
             .select("growth_yoy,growth_yoy_ss,peak_months")
             .eq("trend_key", f"{city_id}|{_norm(row.get('category') or '')}")
             .limit(1).execute().data or [])
    # brand footprint (site size + the three mention signals) — cached
    # context per competitor; best-effort, the brief never breaks over it
    try:
        from services.leadoff_brand import brand_key, footprint_lookups
        site_lookup, mention_rows = footprint_lookups(comps)
        for c in comps:
            c["site_pages"] = site_lookup.get((c.get("domain") or "").strip())
            m = mention_rows.get(brand_key(c.get("business_name") or "")) or {}
            c["mentions"] = m.get("citations")
            c["unlinked_mentions"] = m.get("unlinked_mentions")
            c["nap_citations"] = m.get("nap_citations")
            c["generic_name"] = m.get("generic_name")
    except Exception:
        import logging
        logging.getLogger(__name__).warning("leadoff.footprint_lookup_failed",
                                            exc_info=True)
    brief = attach_permits([{
        **row,
        "competitors": comps,
        "enrichment": enrichment_from_caches(comps, rd_rows, review_rows,
                                             trend[0] if trend else None,
                                             city_id),
    }])[0]
    return _enrich_brief_grade(brief, comps, city_id, category_id,
                              trend[0] if trend else None)


def _enrich_brief_grade(brief: dict[str, Any], comps: list[dict[str, Any]],
                        city_id: int, category_id: str,
                        trend_row: dict[str, Any] | None) -> dict[str, Any]:
    """Promote today's context signals into the brief's grade (owner ruling
    2026-07-12), full four-signal — everything is already loaded here. Proximity
    is computed inline (single market, $0). Best-effort: any failure leaves the
    base grade untouched."""
    from config import settings
    if not settings.leadoff_scoring_enabled:
        return brief
    try:
        from services import leadoff_scoring
        from services.leadoff_proximity import market_proximity_score

        # sync score (no pin naming) — safe to call from the sync brief path
        prox_opp = market_proximity_score(city_id, category_id)
        signals = leadoff_scoring.brief_signals(
            brief, comps, prox_opp,
            (trend_row or {}).get("growth_yoy_ss"))
        lv = _lead_values(DEFAULT_TIER).get(brief.get("category"))
        return leadoff_scoring.enrich_grade(
            brief, signals, capture=DEFAULT_CAPTURE, lead_value=lv,
            breakpoints=_percentile_breakpoints())
    except Exception:
        import logging
        logging.getLogger(__name__).warning("leadoff.brief_enrich_failed",
                                            exc_info=True)
        return brief
