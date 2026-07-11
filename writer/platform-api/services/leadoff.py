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
    matched = False
    for c in competitors:
        v = vel_by_key.get(f"{_norm(c.get('business_name') or '')}|{city_id}")
        if v:
            matched = True
            last30 += int(v.get("last30") or 0)
            prior30 += int(v.get("prior30") or 0)
            if v.get("newest"):
                newest.append(str(v["newest"]))
    if not rds and not matched and not trend_row:
        return None
    momentum = None
    if matched:
        momentum = ("accel" if last30 > prior30 * 1.3
                    else "cooling" if last30 < prior30 * 0.7 else "steady") \
            if (last30 or prior30) else "dead"
    return {
        "rd_min": min(rds) if rds else None,
        "rd_med": sorted(rds)[len(rds) // 2] if rds else None,
        "field_vel30": last30 if matched else None,
        "field_prior30": prior30 if matched else None,
        "momentum": momentum,
        "newest_review": max(newest) if newest else None,
        "growth_yoy": (trend_row or {}).get("growth_yoy"),
        "peak_months": (trend_row or {}).get("peak_months"),
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
    return {"markets": rows[:limit], "as_of": as_of,
            "assumptions": {"capture": capture, "lead_tier": lead_tier,
                            "approximate": not default_assumptions}}


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
             .select("growth_yoy,peak_months")
             .eq("trend_key", f"{city_id}|{_norm(row.get('category') or '')}")
             .limit(1).execute().data or [])
    return {
        **row,
        "competitors": comps,
        "enrichment": enrichment_from_caches(comps, rd_rows, review_rows,
                                             trend[0] if trend else None,
                                             city_id),
    }
