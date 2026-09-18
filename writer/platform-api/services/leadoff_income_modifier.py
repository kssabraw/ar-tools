"""LeadOff — the per-market INCOME local modifier on CPL (valuation plan v1.5).

The counterpart to the CPC modifier (``services/leadoff_cpc.py``): a SECOND,
bounded, conservative, calibration-tunable signal folded into the CPL local
modifier. A market whose median household income sits **above** the national
median gets a premium (higher-ticket jobs, more affluent customers), **below**
it a discount — the ``income ÷ national_median`` ratio, clamped (plan §3):

    income_modifier(city, cat) = clamp(city_income ÷ national_median, lo, hi)

- ``city_income`` is per-city median household income from the app-owned
  ``public.city_household_income`` (the ``leadoff_income`` ACS-B19013 backfill —
  live for ~3.7k board cities, keyed by ``city_id``). Same $0, keyless Census
  source the proximity/placement work already uses; a scanner reload can't touch
  a ``public.*`` table.
- The reference is a NATIONAL median (a single config scalar ≈ the US ACS
  median), so the modifier reads as "this metro runs richer/poorer than the
  country," bidirectionally.
- Degrades to **absent** (``None`` → ×1.0 contribution) on any missing/thin
  income — a missing signal never penalizes a market (the LeadOff "a missing
  signal is not a weak one" rule).

**Blending with the CPC modifier** (``combine``): a **renormalizing weighted-
deviation average** of whichever signals are PRESENT. A single present signal is
returned UNCHANGED, so when income is absent/disabled the combined multiplier is
**byte-identical to the CPC-only v1 behavior**; with both present the combined
swing stays between the two individual modifiers (conservative — never more
extreme than either), then clamped to the widest of the two bounds so a single
signal is never clipped.

Pure ``income_modifier`` / ``combine`` / ``local_modifier`` unit-tested in
``tests/test_leadoff_income_modifier.py``; the impure income read isolates its
DB access.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

INCOME_TABLE = "city_household_income"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def income_modifier(city_income: Optional[float],
                    national_median_income: Optional[float],
                    *, lo: float, hi: float, min_income: float) -> Optional[float]:
    """The income CPL multiplier for one market (pure). ``None`` (absent) when
    either value is missing or below ``min_income`` (a tiny/sentinel income is
    noise or bad ACS data), else ``clamp(city ÷ national, lo, hi)`` rounded to 3.
    Bidirectional: a below-median metro returns < 1 (discount), above-median
    returns > 1 (premium)."""
    try:
        c = float(city_income) if city_income is not None else None
        n = float(national_median_income) if national_median_income is not None else None
    except (TypeError, ValueError):
        return None
    if c is None or n is None or c < min_income or n < min_income:
        return None
    return round(_clamp(c / n, lo, hi), 3)


def combine(signals: list[tuple[Optional[float], float]], *,
            lo: float, hi: float) -> float:
    """Blend per-signal multipliers into one CPL multiplier (pure).

    ``signals`` is ``[(modifier_or_None, weight), ...]``; a signal is PRESENT when
    its modifier is not None and its weight > 0. Rules:

    - No present signal → ``1.0``.
    - Exactly one present → that modifier UNCHANGED (no arithmetic), which is why
      CPC-only stays byte-identical to v1 when income is absent/disabled.
    - Two+ present → ``1 + Σ(w·(m−1)) ÷ Σw`` (a weighted average of each signal's
      deviation from 1, weights renormalized over the present set), clamped to
      ``[lo, hi]`` and rounded to 3. The result always lies between the smallest
      and largest present modifier, so blending can never be MORE extreme than a
      single signal — the conservative property.
    """
    present = [(m, w) for m, w in signals if m is not None and w > 0]
    if not present:
        return 1.0
    if len(present) == 1:
        return present[0][0]
    wsum = sum(w for _, w in present)
    dev = sum(w * (m - 1.0) for m, w in present) / wsum
    return round(_clamp(1.0 + dev, lo, hi), 3)


def enabled() -> bool:
    from config import settings
    return bool(settings.leadoff_income_modifier_enabled)


def params() -> dict[str, Any]:
    """The full bundle the callers need for one ``local_modifier`` call: CPC
    bounds (reused from ``leadoff_cpc``) + income bounds + weights + national
    median + the enabled gate + the widest-of-both total clamp. Kept out of the
    pure fns so they stay testable without config."""
    from config import settings

    from services import leadoff_cpc
    cpc_b = leadoff_cpc.bounds()  # {lo, hi, min_cpc}
    inc_lo = float(settings.leadoff_income_modifier_min)
    inc_hi = float(settings.leadoff_income_modifier_max)
    return {
        "enabled": bool(settings.leadoff_income_modifier_enabled),
        "cpc_lo": cpc_b["lo"], "cpc_hi": cpc_b["hi"], "cpc_min_cpc": cpc_b["min_cpc"],
        "inc_lo": inc_lo, "inc_hi": inc_hi,
        "min_income": float(settings.leadoff_income_modifier_min_income),
        "national_median": float(settings.leadoff_income_national_median),
        "w_cpc": float(settings.leadoff_local_modifier_weight_cpc),
        "w_income": float(settings.leadoff_local_modifier_weight_income),
        # total clamp = widest of the two so a lone present signal is never
        # clipped (→ CPC-only byte-identical, income-only unclipped).
        "total_lo": min(cpc_b["lo"], inc_lo),
        "total_hi": max(cpc_b["hi"], inc_hi),
    }


def local_modifier(market_cpc: Optional[float], category_name: Optional[str],
                   city_income: Optional[float], cpc_baseline: dict[str, float],
                   p: dict[str, Any]) -> tuple[float, dict[str, Optional[float]]]:
    """The combined per-market CPL multiplier + a detail dict of which signals fed
    it (plan §3 transparency). Pure given its inputs — the caller loads
    ``cpc_baseline`` (leadoff_cpc.baseline_map), ``p`` (params) and the city income
    once. When income is disabled (``p['enabled']`` False) the income signal is
    dropped, so the result is byte-identical to the CPC-only v1 modifier."""
    from services import leadoff_cpc
    med = cpc_baseline.get(str(category_name or "").lower()) if category_name else None
    cpc_mod = leadoff_cpc.cpc_modifier_opt(
        market_cpc, med, lo=p["cpc_lo"], hi=p["cpc_hi"], min_cpc=p["cpc_min_cpc"])
    inc_mod = (income_modifier(city_income, p["national_median"], lo=p["inc_lo"],
                               hi=p["inc_hi"], min_income=p["min_income"])
               if p.get("enabled") else None)
    combined = combine([(cpc_mod, p["w_cpc"]), (inc_mod, p["w_income"])],
                       lo=p["total_lo"], hi=p["total_hi"])
    return combined, {"cpc": cpc_mod, "income": inc_mod}


# ── Income read (impure — public.city_household_income) ────────────────────────

def income_map(city_ids: list[int]) -> dict[int, int]:
    """{city_id: median_household_income} for the given board cities, read from
    public.city_household_income. {} when disabled, empty input, or on any read
    failure → the income signal degrades to absent (×1.0). Best-effort."""
    if not enabled() or not city_ids:
        return {}
    try:
        from db.supabase_client import get_supabase
        ids = list({int(c) for c in city_ids if c is not None})
        out: dict[int, int] = {}
        for i in range(0, len(ids), 500):  # .in_() batched (grade-all can be large)
            rows = (get_supabase().table(INCOME_TABLE)
                    .select("city_id,median_household_income")
                    .in_("city_id", ids[i:i + 500]).execute().data or [])
            for r in rows:
                v = r.get("median_household_income")
                if v is not None:
                    out[int(r["city_id"])] = int(v)
        return out
    except Exception:
        logger.warning("leadoff_income_modifier.income_read_failed", exc_info=True)
        return {}


def city_income(city_id: Optional[int]) -> Optional[int]:
    """Median household income for one city, or None (absent). Best-effort."""
    if city_id is None:
        return None
    return income_map([int(city_id)]).get(int(city_id))
