"""LeadOff — the per-market CPC local modifier on CPL (valuation plan v1, step 2).

The grader already pulls a per-``city × category`` Google Ads **CPC**
(``leadoff_actions.demand_from_items``) and then **discards it** from the value
calc, so a painting lead in Manhattan and in Mobile grade with the identical flat
national CPL. This restores that signal as a **bounded, conservative, calibration-
tunable** multiplier on the CPL (plan §3):

    CPL(city, cat) = national_anchor(cat) × clamp(market_cpc ÷ national_median_cpc(cat), min, max)

- ``national_median_cpc(cat)`` is precomputed board-wide into the app-owned
  ``public.leadoff_cpc_baseline`` (median of ``market_opportunity_master``'s
  ``category_cpc`` per category) — a scanner reload can't touch it, and it costs
  no paid call. Populated by ``scripts/build_cpc_baseline.py``; **inert (×1.0)
  until it is, so shipping the mechanic changes nothing until it's activated.**
- Degrades to **×1.0** on any missing/thin CPC (either the market's live CPC or
  the national median below ``min_cpc``) — a missing signal never penalizes a
  market (the LeadOff "a missing signal is not a weak one" rule).
- Applied on the **live grade paths** (tryout / grade / grade-all), where a live
  CPC is in hand; the precomputed board stays a national-anchor view.

Pure ``cpc_modifier`` unit-tested in ``tests/test_leadoff_cpc.py``; the impure
baseline read/refresh isolates its DB access.
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASELINE_TABLE = "leadoff_cpc_baseline"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def cpc_modifier(market_cpc: Optional[float], national_median_cpc: Optional[float],
                 *, lo: float, hi: float, min_cpc: float) -> float:
    """The CPL multiplier for one market (pure). ×1.0 when either CPC is
    absent or below ``min_cpc`` (a sub-dollar CPC ratio is noise), else the
    market ÷ national ratio clamped to [lo, hi]."""
    try:
        m = float(market_cpc) if market_cpc is not None else None
        n = float(national_median_cpc) if national_median_cpc is not None else None
    except (TypeError, ValueError):
        return 1.0
    if m is None or n is None or m < min_cpc or n < min_cpc:
        return 1.0
    return round(_clamp(m / n, lo, hi), 3)


def cpc_modifier_opt(market_cpc: Optional[float], national_median_cpc: Optional[float],
                     *, lo: float, hi: float, min_cpc: float) -> Optional[float]:
    """Like ``cpc_modifier`` but returns ``None`` when the signal is ABSENT (either
    CPC missing or below ``min_cpc``), vs the ``1.0`` that ``cpc_modifier`` returns
    for both 'absent' AND 'market == national'. The distinction matters only when
    BLENDING with a second signal (leadoff_income_modifier): an absent CPC must
    hand full weight to the other signal, whereas a genuine 1.0 (market == national)
    is a real, weighted contribution. When present, this returns the identical value
    to ``cpc_modifier`` (both round to 3), so CPC-only stays byte-identical."""
    try:
        m = float(market_cpc) if market_cpc is not None else None
        n = float(national_median_cpc) if national_median_cpc is not None else None
    except (TypeError, ValueError):
        return None
    if m is None or n is None or m < min_cpc or n < min_cpc:
        return None
    return round(_clamp(m / n, lo, hi), 3)


def bounds() -> dict[str, float]:
    """Config-driven modifier bounds (calibratable). Kept out of the pure fn so
    ``cpc_modifier`` stays testable without config."""
    from config import settings
    return {"lo": float(settings.leadoff_cpc_modifier_min),
            "hi": float(settings.leadoff_cpc_modifier_max),
            "min_cpc": float(settings.leadoff_cpc_modifier_min_cpc)}


def enabled() -> bool:
    from config import settings
    return bool(settings.leadoff_cpc_modifier_enabled)


def baseline_map() -> dict[str, float]:
    """National median CPC per category (lowercased category name → median_cpc),
    read from public.leadoff_cpc_baseline. {} when disabled or unpopulated → the
    modifier is a no-op (×1.0 everywhere). Best-effort: any read failure → {}."""
    if not enabled():
        return {}
    try:
        from db.supabase_client import get_supabase
        rows = (get_supabase().table(BASELINE_TABLE)
                .select("category_name,median_cpc").execute().data or [])
        return {str(r["category_name"]).lower(): float(r["median_cpc"])
                for r in rows if r.get("median_cpc") is not None}
    except Exception:
        logger.warning("leadoff_cpc.baseline_read_failed", exc_info=True)
        return {}


def modifier_for(market_cpc: Optional[float], category_name: Optional[str],
                 baseline: dict[str, float], b: dict[str, float]) -> float:
    """Resolve the multiplier for one market from a loaded baseline map + bounds
    (looks the national median up by lowercased category name). Pure given its
    inputs — the caller loads ``baseline`` (baseline_map) + ``b`` (bounds) once."""
    med = baseline.get(str(category_name or "").lower()) if category_name else None
    return cpc_modifier(market_cpc, med, **b)


# ── Baseline compute (impure — reads master, upserts public.leadoff_cpc_baseline)

def compute_baseline_rows(master_rows: list[dict[str, Any]],
                          cat_id_to_name: dict[Any, str]) -> list[dict[str, Any]]:
    """Median ``category_cpc`` per category name over the master rows (pure).
    Rows carry median_cpc + n so a thin category is inspectable. Categories with
    no positive CPC are skipped (they'd yield a ×1.0 lookup anyway)."""
    by_cat: dict[str, list[float]] = {}
    for r in master_rows:
        name = cat_id_to_name.get(r.get("category_id"))
        cpc = r.get("category_cpc")
        if not name or cpc is None:
            continue
        try:
            v = float(cpc)
        except (TypeError, ValueError):
            continue
        if v > 0:
            by_cat.setdefault(name, []).append(v)
    return [{"category_name": name, "median_cpc": round(median(vals), 2),
             "n": len(vals)}
            for name, vals in sorted(by_cat.items()) if vals]
