"""Deterministic forecasting (strategist roadmap phase 3).

Projects where the campaign is heading — and what winning would be worth —
from data the suite already stores. Three reads:

  * RANK TRAJECTORIES: least-squares trend over each keyword's recent
    position series (one source only — GSC weighted positions or the
    DataForSEO tracked rank, never spliced), projected 30/90 days out with
    a confidence grade from data density.
  * TRAFFIC / VALUE: a standard position→CTR curve × cached search volume ×
    CPC. GSC-covered keywords use their ACTUAL 30-day clicks as the current
    number (the model only scales it for projections); model-only keywords
    are labeled as estimates.
  * SCENARIOS: "winning these striking-distance keywords to top 3 ≈
    +X clicks/mo ≈ $Y/mo" — the quick-win upside, per keyword and summed.
  * GOAL PROJECTIONS: for campaign goals with a due date, whether the
    current trajectory reaches the target in time.

Everything is computed on read (nothing stored, no new capture, market data
comes from the existing keyword_market cache — cache-only, no paid calls).
The LLM surfaces (digest, Slack) receive finished numbers with trap notes;
they never do the arithmetic. Linear extrapolation is direction+magnitude
guidance, not a promise — every surface carries that caveat.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Position → expected organic CTR. A standard industry-shape curve (top-heavy,
# long thin tail); treat as a MODEL, not ground truth — GSC actuals are used
# instead wherever they exist.
CTR_CURVE: dict[int, float] = {
    1: 0.28, 2: 0.155, 3: 0.105, 4: 0.077, 5: 0.061,
    6: 0.047, 7: 0.038, 8: 0.032, 9: 0.028, 10: 0.024,
}
_CTR_11_20 = 0.013
_CTR_21_30 = 0.007
_CTR_BEYOND = 0.003

_MIN_TREND_POINTS = 4
_MIN_TREND_SPAN_DAYS = 14
_STRIKING_DISTANCE = (4.0, 20.0)   # quick-win band (below the fold → page 2)
_QUICK_WIN_TARGET = 3


# ---------------------------------------------------------------------------
# Pure model (unit-tested)
# ---------------------------------------------------------------------------
def ctr_for_position(position: Optional[float]) -> float:
    """Expected CTR at a (possibly fractional) position. Pure."""
    if position is None or position < 1:
        position = 1.0
    lo = int(position)
    if lo >= 30:
        return _CTR_BEYOND
    if lo >= 20:
        return _CTR_21_30
    if lo >= 10 and lo not in CTR_CURVE:
        return _CTR_11_20
    hi = lo + 1
    lo_ctr = CTR_CURVE.get(lo, _CTR_11_20)
    hi_ctr = CTR_CURVE.get(hi, _CTR_11_20 if hi <= 20 else _CTR_21_30)
    frac = position - lo
    return round(lo_ctr + (hi_ctr - lo_ctr) * frac, 4)


def fit_trend(points: list[tuple[int, float]]) -> Optional[float]:
    """Least-squares slope (position change per day) over (day_ordinal, position)
    points. None when too thin to trust (<4 points or <14-day span). Pure.
    Negative slope = improving (position falling)."""
    pts = [(d, p) for d, p in points if p is not None]
    if len(pts) < _MIN_TREND_POINTS:
        return None
    days = [d for d, _ in pts]
    if max(days) - min(days) < _MIN_TREND_SPAN_DAYS:
        return None
    n = len(pts)
    mean_x = sum(d for d, _ in pts) / n
    mean_y = sum(p for _, p in pts) / n
    denom = sum((d - mean_x) ** 2 for d, _ in pts)
    if denom == 0:
        return None
    slope = sum((d - mean_x) * (p - mean_y) for d, p in pts) / denom
    return slope


def project_position(current: Optional[float], slope_per_day: Optional[float], days: int) -> Optional[float]:
    """Linear projection, clamped to [1, 100]. None without a current read.
    A None slope projects flat (no trend evidence ≠ no position). Pure."""
    if current is None:
        return None
    projected = current + (slope_per_day or 0.0) * days
    return round(min(100.0, max(1.0, projected)), 1)


def trend_confidence(points: list[tuple[int, float]]) -> str:
    """high / medium / low from data density + span. Pure."""
    pts = [(d, p) for d, p in points if p is not None]
    if not pts:
        return "low"
    span = max(d for d, _ in pts) - min(d for d, _ in pts)
    if len(pts) >= 20 and span >= 45:
        return "high"
    if len(pts) >= 8 and span >= 21:
        return "medium"
    return "low"


def forecast_keyword(
    keyword: str,
    points: list[tuple[int, float]],
    current_position: Optional[float],
    actual_clicks_30d: Optional[int],
    volume: Optional[int],
    cpc: Optional[float],
    clicks_source: str,
) -> dict:
    """One keyword's trajectory + traffic/value read. Pure."""
    slope = fit_trend(points)
    proj_30 = project_position(current_position, slope, 30)
    proj_90 = project_position(current_position, slope, 90)

    cur_ctr = ctr_for_position(current_position) if current_position is not None else None
    if clicks_source == "gsc" and actual_clicks_30d is not None:
        clicks_now: Optional[float] = float(actual_clicks_30d)
    elif volume is not None and cur_ctr is not None:
        clicks_now = round(volume * cur_ctr, 1)
    else:
        clicks_now = None

    clicks_90: Optional[float] = None
    if clicks_now is not None and proj_90 is not None and cur_ctr:
        # Scale the current read by the CTR ratio — keeps GSC actuals anchored.
        clicks_90 = round(clicks_now * ctr_for_position(proj_90) / cur_ctr, 1)

    return {
        "keyword": keyword,
        "current_position": current_position,
        "trend_per_week": round(slope * 7, 2) if slope is not None else None,  # negative = improving
        "projected_position_30d": proj_30,
        "projected_position_90d": proj_90,
        "confidence": trend_confidence(points),
        "clicks_per_month_now": clicks_now,
        "clicks_per_month_90d": clicks_90,
        "clicks_source": clicks_source if clicks_now is not None else "none",
        "search_volume": volume,
        "cpc": cpc,
        "value_per_month_now": round(clicks_now * cpc, 0) if clicks_now is not None and cpc else None,
        "value_per_month_90d": round(clicks_90 * cpc, 0) if clicks_90 is not None and cpc else None,
    }


def quick_win_scenario(forecasts: list[dict], target: int = _QUICK_WIN_TARGET) -> dict:
    """The upside of moving every striking-distance keyword to `target`:
    volume × (ctr(target) − ctr(current)), valued at CPC. CTR-model numbers
    (needs volume — keywords without market data are skipped and counted). Pure."""
    lo, hi = _STRIKING_DISTANCE
    items: list[dict] = []
    skipped_no_volume = 0
    for f in forecasts:
        pos = f.get("current_position")
        if pos is None or not (lo <= pos <= hi):
            continue
        vol = f.get("search_volume")
        if not vol:
            skipped_no_volume += 1
            continue
        delta_ctr = ctr_for_position(target) - ctr_for_position(pos)
        if delta_ctr <= 0:
            continue
        extra_clicks = round(vol * delta_ctr, 1)
        cpc = f.get("cpc")
        items.append({
            "keyword": f["keyword"],
            "current_position": pos,
            "target_position": target,
            "extra_clicks_per_month": extra_clicks,
            "extra_value_per_month": round(extra_clicks * cpc, 0) if cpc else None,
        })
    items.sort(key=lambda i: -(i.get("extra_value_per_month") or i["extra_clicks_per_month"] or 0))
    return {
        "target_position": target,
        "keywords": items,
        "keyword_count": len(items),
        "total_extra_clicks_per_month": round(sum(i["extra_clicks_per_month"] for i in items), 0),
        "total_extra_value_per_month": round(
            sum(i["extra_value_per_month"] or 0 for i in items), 0
        ),
        "skipped_no_volume": skipped_no_volume,
    }


def project_metric_linear(
    current_window: float, previous_window: float, windows_ahead: float
) -> float:
    """Project a windowed metric (e.g. 30-day clicks) forward at its current
    window-over-window delta. Never below zero. Pure."""
    delta = current_window - previous_window
    return max(0.0, current_window + delta * windows_ahead)


def goal_projection(goal: dict, keyword_forecasts: dict[str, dict], today: date) -> Optional[dict]:
    """Whether a goal's current trajectory reaches its target by the due date.
    Only for goal types a deterministic trajectory exists for. Pure."""
    due = goal.get("due_date")
    try:
        due_date = date.fromisoformat(str(due)[:10]) if due else None
    except ValueError:
        due_date = None
    horizon_days = (due_date - today).days if due_date else 90
    if horizon_days <= 0:
        return None

    if goal.get("goal_type") == "keyword_position":
        f = keyword_forecasts.get((goal.get("keyword") or "").strip().casefold())
        if not f or f.get("current_position") is None:
            return None
        slope = (f.get("trend_per_week") or 0.0) / 7.0
        projected = project_position(f["current_position"], slope, horizon_days)
        target = goal.get("target_value")
        will_meet = projected is not None and target is not None and projected <= target
        return {
            "goal_label": goal.get("label"),
            "horizon_days": horizon_days,
            "projected_value": projected,
            "target_value": target,
            "on_trajectory": will_meet,
            "confidence": f.get("confidence"),
        }
    return None


# ---------------------------------------------------------------------------
# Assembly (DB reads; market from cache only — no paid calls)
# ---------------------------------------------------------------------------
def build_forecast(client_id: str, today: Optional[date] = None) -> dict:
    """The full client forecast: per-keyword trajectories, portfolio totals,
    the quick-win scenario, GSC clicks trajectory, and goal projections."""
    from config import settings
    from services import rank_status
    from services.dataforseo_rank import location_code_for
    from services.keyword_market import fetch_cached_market

    supabase = get_supabase()
    today = today or date.today()

    client = (
        supabase.table("clients").select("*").eq("id", client_id).limit(1).execute()
    ).data or [{}]
    kws = (
        supabase.table("tracked_keywords").select("id, keyword")
        .eq("client_id", client_id).eq("active", True).order("keyword").execute()
    ).data or []

    forecasts: list[dict] = []
    if kws:
        kw_ids = [k["id"] for k in kws]
        cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
        metrics: dict[str, list[dict]] = {}
        for r in (
            supabase.table("rank_keyword_metrics")
            .select("keyword_id, date, gsc_position, tracked_rank, clicks, impressions")
            .in_("keyword_id", kw_ids).gte("date", cutoff).execute()
        ).data or []:
            metrics.setdefault(r["keyword_id"], []).append(r)

        try:
            market = fetch_cached_market(
                supabase, [k["keyword"] for k in kws], location_code_for(client[0])
            )
        except Exception:
            market = {}

        for k in kws:
            rows = metrics.get(k["id"], [])
            s = rank_status.compute_keyword_summary(rows, today, settings.rank_gsc_coverage_days)
            source = s.get("primary_source")
            # One source only for the trend series — never splice GSC + DataForSEO.
            field = "gsc_position" if source == "gsc" else "tracked_rank"
            points = [
                (date.fromisoformat(str(r["date"])[:10]).toordinal(), r.get(field))
                for r in rows if r.get("date") and r.get(field) is not None
            ]
            current = s.get("avg_7") if source == "gsc" else s.get("today_rank")
            m = market.get(k["keyword"].lower()) or {}
            forecasts.append(forecast_keyword(
                keyword=k["keyword"],
                points=points,
                current_position=float(current) if current is not None else None,
                actual_clicks_30d=s.get("clicks_30d") if source == "gsc" else None,
                volume=m.get("search_volume"),
                cpc=m.get("cpc"),
                clicks_source="gsc" if source == "gsc" else "ctr_model",
            ))

    # Portfolio totals (only keywords with a clicks read).
    clicks_now = sum(f["clicks_per_month_now"] or 0 for f in forecasts)
    clicks_90 = sum(
        (f["clicks_per_month_90d"] if f["clicks_per_month_90d"] is not None
         else f["clicks_per_month_now"]) or 0
        for f in forecasts
    )
    value_now = sum(f["value_per_month_now"] or 0 for f in forecasts)
    value_90 = sum(
        (f["value_per_month_90d"] if f["value_per_month_90d"] is not None
         else f["value_per_month_now"]) or 0
        for f in forecasts
    )

    # GSC property-level clicks trajectory (all queries, not just tracked).
    gsc_trajectory: Optional[dict] = None
    try:
        prop = (
            supabase.table("gsc_properties").select("id")
            .eq("client_id", client_id).eq("access_status", "ok").limit(1).execute()
        ).data
        if prop:
            cur_cut = date.fromordinal(today.toordinal() - 30).isoformat()
            prev_cut = date.fromordinal(today.toordinal() - 60).isoformat()
            rows = (
                supabase.table("gsc_query_daily").select("date, clicks")
                .eq("property_id", prop[0]["id"]).gte("date", prev_cut).execute()
            ).data or []
            cur = sum(r.get("clicks") or 0 for r in rows if str(r.get("date")) >= cur_cut)
            prev = sum(r.get("clicks") or 0 for r in rows if str(r.get("date")) < cur_cut)
            gsc_trajectory = {
                "clicks_last_30d": cur,
                "clicks_previous_30d": prev,
                "delta_30d": cur - prev,
                "projected_30d_ahead": round(project_metric_linear(cur, prev, 1)),
                "projected_90d_ahead": round(project_metric_linear(cur, prev, 3)),
            }
    except Exception as exc:
        logger.warning("forecasting.gsc_trajectory_failed", extra={"client_id": client_id, "error": str(exc)})

    # Goal projections.
    goal_projections: list[dict] = []
    try:
        from services import campaign_goals

        by_kw = {f["keyword"].casefold(): f for f in forecasts}
        for g in campaign_goals.assess_goals(client_id, today=today):
            if g.get("status") in ("achieved", "manual"):
                continue
            proj = goal_projection(g, by_kw, today)
            if proj:
                goal_projections.append(proj)
            elif g.get("goal_type") == "organic_clicks" and gsc_trajectory and g.get("due_date"):
                try:
                    horizon = (date.fromisoformat(str(g["due_date"])[:10]) - today).days
                except ValueError:
                    continue
                if horizon <= 0:
                    continue
                projected = round(project_metric_linear(
                    gsc_trajectory["clicks_last_30d"],
                    gsc_trajectory["clicks_previous_30d"],
                    horizon / 30.0,
                ))
                target = g.get("target_value")
                goal_projections.append({
                    "goal_label": g.get("label"),
                    "horizon_days": horizon,
                    "projected_value": projected,
                    "target_value": target,
                    "on_trajectory": target is not None and projected >= target,
                    "confidence": "medium" if gsc_trajectory["clicks_previous_30d"] else "low",
                })
    except Exception as exc:
        logger.warning("forecasting.goal_projection_failed", extra={"client_id": client_id, "error": str(exc)})

    forecasts.sort(key=lambda f: -((f.get("value_per_month_90d") or 0) - (f.get("value_per_month_now") or 0)))
    return {
        "generated_for": today.isoformat(),
        "keyword_count": len(forecasts),
        "keywords": forecasts,
        "portfolio": {
            "clicks_per_month_now": round(clicks_now),
            "clicks_per_month_90d": round(clicks_90),
            "value_per_month_now": round(value_now),
            "value_per_month_90d": round(value_90),
        },
        "quick_wins": quick_win_scenario(forecasts),
        "gsc_clicks_trajectory": gsc_trajectory,
        "goal_projections": goal_projections,
        "note": (
            "Projections are linear extrapolations of the recent trend — direction "
            "and magnitude guidance, not promises. clicks_source='gsc' rows anchor "
            "on actual Search Console clicks; 'ctr_model' rows are volume × a "
            "standard CTR curve. Quick-win math is CTR-model throughout."
        ),
    }
