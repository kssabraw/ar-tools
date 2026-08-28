"""LeadOff — agency cost-to-win ROI (owner ruling 2026-08-28).

Replaces the mislabelled "ROI ($/mo per review)" — which was a value-per-effort
ratio, never a real ROI because it subtracts no cost — with a **true economic
ROI**: the market's expected monthly value measured against what the AGENCY
actually pays to win and hold the ranking (links + content + reviews + monthly
maintenance). Owner decisions:
  * Cost basis = **agency cost-to-win** (what we pay to deliver the work), the
    right question for a pre-client market-entry scanner ("is this market worth
    US building").
  * Headline = **both** the monthly profit ($/mo) AND the payback period
    (months to recoup the one-time catch-up cost from that profit).

Unit prices come from the **Recipe Engine** catalog (`services/recipe_engine`)
so LeadOff never invents a dollar figure — `CONTENT_PAGE_COST` is imported, and
the monthly-maintenance / per-review / per-link defaults live in config sourced
from the same SOP pricing (tunable independently: a market-selection forecast
may assume differently than a live campaign).

**Pre-client honesty.** reviews-to-win + the unit costs are solid; the RD/link
gap is only captured on **scouted** markets (board-wide it's modelled), and
pages-to-rank is an assumption — so every result carries `roi_confidence`
('measured' once a real RD gap is supplied, else 'modelled') and a
`roi_links_estimated` flag, and the number is a forecast that sharpens
post-scout / post-client. The old `roi` ($/review) is preserved on the row for
back-compat + a tooltip.

Pure core (`compute_roi`, unit-tested `tests/test_leadoff_roi.py`); `attach_roi`
is the thin impure adapter that reads config.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def compute_roi(exp_val: Optional[float], rev_win: Optional[float], *,
                cost_per_review: float, cost_per_link: float,
                content_pages: float, content_page_cost: float,
                monthly_maintenance: float, ramp_months: float = 0.0,
                first_month_multiplier: float = 1.0,
                rd_gap_true: Optional[float] = None) -> dict[str, Any]:
    """Agency cost-to-win economics from a market's expected monthly value and
    its winnability gaps. Pure — no config, no I/O.

    deliverables      = reviews-to-win × per-review + pages × per-page
        (+ RD gap × per-link, only when a real RD gap is supplied).
    setup surcharge   = (first_month_multiplier − 1) × monthly maintenance — the
        first month costs more (site setup, initial citations, GBP config) than
        the steady-state months.
    ramp cost         = ramp_months × monthly maintenance — the labour paid
        DURING the months-long climb to rank, before any value arrives. This is
        what makes payback realistic (SEO never recoups a real campaign in
        weeks); the full sunk investment to win = deliverables + setup + ramp.
    monthly profit    = expected $/mo − monthly maintenance (steady state, once
        ranked).
    payback (months)  = ramp_months + (deliverables + setup + ramp cost) ÷
        monthly profit — you earn nothing through the ramp, then recoup the sunk
        cost from profit. None ⇒ never pays back (maintenance ≥ market's value).

    Simplification: value is modelled as switching on at the end of the ramp
    (a step, not a gradual climb) — conservative-leaning and honest for a
    pre-client forecast. `rd_gap_true` is the TRUE referring-domain gap to close
    (×10-converted competitor field median, minus the new entrant's ~0) — pass
    it only for scouted markets; omit board-wide and links are 0 + flagged.
    """
    ev = float(exp_val or 0.0)
    reviews_n = max(0.0, float(rev_win or 0.0))
    reviews_cost = reviews_n * cost_per_review
    content_cost = max(0.0, float(content_pages)) * content_page_cost
    links_estimated = rd_gap_true is None
    links_rd = 0.0 if links_estimated else max(0.0, float(rd_gap_true))
    links_cost = links_rd * cost_per_link
    deliverables = reviews_cost + content_cost + links_cost

    monthly_cost = max(0.0, float(monthly_maintenance))
    setup_cost = max(0.0, float(first_month_multiplier) - 1.0) * monthly_cost
    ramp = max(0.0, float(ramp_months))
    ramp_cost = ramp * monthly_cost
    sunk = deliverables + setup_cost + ramp_cost   # total invested before payoff

    monthly_profit = ev - monthly_cost
    payback = (round(ramp + sunk / monthly_profit, 1)
               if monthly_profit > 0 else None)

    return {
        "monthly_profit": round(monthly_profit),
        "monthly_cost": round(monthly_cost),
        "cost_to_win": round(sunk),           # deliverables + setup + ramp labour
        "ramp_months": round(ramp, 1),
        "payback_months": payback,
        "roi_links_estimated": links_estimated,
        "roi_confidence": "modelled" if links_estimated else "measured",
        "cost_breakdown": {
            "reviews": round(reviews_cost),
            "reviews_n": round(reviews_n),
            "content": round(content_cost),
            "content_pages": round(float(content_pages)),
            "links": round(links_cost),
            "links_rd": round(links_rd),
            "setup": round(setup_cost),
            "ramp": round(ramp_cost),
            "deliverables": round(deliverables),
        },
    }


def estimate_ramp_months(*, beatability: Optional[float], rankab: Optional[float],
                         momentum: Optional[str], ramp_min: float, ramp_max: float,
                         accel_mult: float, cooling_mult: float) -> float:
    """Market-specific ramp-to-rank (months). Pure.

    Field difficulty sets the base: a soft field (high Beatability / high
    win-likelihood) ramps near `ramp_min`, a brutal one near `ramp_max`. Then
    the incumbents' own SEO activity adjusts it — an accelerating review field
    (`momentum == 'accel'`) means a moving target → ×`accel_mult`; a cooling or
    dead field → ×`cooling_mult`. `momentum` is None board-wide (no velocity
    cache) → difficulty-only. Beatability preferred; win-likelihood is the
    always-present fallback; 0.5 ease when neither is known.
    """
    if beatability is not None:
        ease = max(0.0, min(1.0, float(beatability) / 100.0))
    elif rankab is not None:
        ease = max(0.0, min(1.0, float(rankab)))
    else:
        ease = 0.5
    base = ramp_max - ease * (ramp_max - ramp_min)
    if momentum == "accel":
        base *= accel_mult
    elif momentum in ("cooling", "dead"):
        base *= cooling_mult
    return round(max(0.0, base), 1)


def estimate_maintenance(*, beatability: Optional[float], rankab: Optional[float],
                         maint_min: float, maint_max: float) -> float:
    """Sliding monthly maintenance (what it costs to HOLD the ranking). Pure.

    Harder fields cost more to defend, so this slides on the same difficulty
    signal as the ramp: a soft field (high Beatability / win-likelihood) sits
    near `maint_min`, a brutal one near `maint_max`. Beatability preferred;
    win-likelihood fallback; midpoint when neither is known.
    """
    if beatability is not None:
        ease = max(0.0, min(1.0, float(beatability) / 100.0))
    elif rankab is not None:
        ease = max(0.0, min(1.0, float(rankab)))
    else:
        ease = 0.5
    return round(maint_min + (1.0 - ease) * (maint_max - maint_min))


def roi_params() -> dict[str, float]:
    """The config-sourced cost assumptions (impure). Content page price comes
    straight from the Recipe Engine so it can't drift from the SOP catalog."""
    from config import settings
    from services.recipe_engine import CONTENT_PAGE_COST
    return {
        "cost_per_review": settings.leadoff_roi_cost_per_review,
        "cost_per_link": settings.leadoff_roi_cost_per_link,
        "content_pages": settings.leadoff_roi_content_pages,
        "content_page_cost": CONTENT_PAGE_COST,
        "first_month_multiplier": settings.leadoff_roi_first_month_multiplier,
    }


def attach_roi(row: dict[str, Any], *,
               rd_gap_true: Optional[float] = None) -> dict[str, Any]:
    """Merge the cost-to-win ROI fields onto a board/brief row from its stored
    `exp_val` + `rev_win`. Impure (reads config); gated on
    `leadoff_roi_enabled` (off ⇒ row unchanged, old `roi` stays). Never raises —
    a bad row degrades to the untouched row."""
    from config import settings
    if not settings.leadoff_roi_enabled:
        return row
    try:
        # Market-specific ramp from field difficulty (Beatability / win-
        # likelihood) + the incumbents' review-velocity momentum (scouted only,
        # carried on the brief's enrichment block; None board-wide).
        momentum = (row.get("enrichment") or {}).get("momentum")
        bt, ra = row.get("beatability"), row.get("rankab")
        ramp = estimate_ramp_months(
            beatability=bt, rankab=ra, momentum=momentum,
            ramp_min=settings.leadoff_roi_ramp_min_months,
            ramp_max=settings.leadoff_roi_ramp_max_months,
            accel_mult=settings.leadoff_roi_ramp_accel_mult,
            cooling_mult=settings.leadoff_roi_ramp_cooling_mult)
        maintenance = estimate_maintenance(
            beatability=bt, rankab=ra,
            maint_min=settings.leadoff_roi_maint_min_month,
            maint_max=settings.leadoff_roi_maint_max_month)
        roi = compute_roi(row.get("exp_val"), row.get("rev_win"),
                          ramp_months=ramp, monthly_maintenance=maintenance,
                          rd_gap_true=rd_gap_true, **roi_params())
        return {**row, **roi}
    except Exception:
        logger.warning("leadoff_roi.attach_failed", exc_info=True)
        return row


def rd_gap_from_enrichment(enrichment: Optional[dict[str, Any]], *,
                           mult: Optional[float] = None) -> Optional[float]:
    """True RD gap for the ROI link component from a brief's enrichment block:
    the competitor field median RD (`rd_med`, a tool read → ×10 true RD) that a
    new entrant (≈0 RD) must close, scaled by `leadoff_roi_rd_target_mult`.
    None when no RD is cached (unscouted) → the ROI stays modelled. Pure-ish
    (reads one config default)."""
    if not enrichment:
        return None
    rd_med = enrichment.get("rd_med")
    if rd_med is None:
        return None
    if mult is None:
        from config import settings
        mult = settings.leadoff_roi_rd_target_mult
    return max(0.0, float(rd_med) * 10.0 * float(mult))
