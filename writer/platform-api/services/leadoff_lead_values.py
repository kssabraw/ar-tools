"""LeadOff — the exclusive-CPL re-anchor ladder (valuation plan v1, step 1).

Recalibrates ``market_scanner.lead_values`` from its flat, source-less, *shared*-
anchored manual estimates to **exclusive** cost-per-lead values grounded in real
network rate cards + HomeAdvisor job values (owner's Drive spec
``lead_pricing_data_spec.md``), per the §4 confidence-tiered ladder of
``docs/modules/leadoff-valuation-plan-v1_0.md``.

Why: the grade's value is ``leads × CPL`` and the manual CPLs were anchored to
shared-lead (low) economics, so the board **under-ranks the high-ticket emergency
trades** a rank-and-rent operator most wants (water damage $138 mid vs a real
exclusive range $500–2,250). Re-anchoring to exclusive prices lifts exactly those.

The ladder (each output row records ``source`` + ``confidence`` — **nothing is
fabricated**; a niche with no defensible signal keeps its flagged manual estimate):

  1. **Direct exclusive range** (``service_direct_range``, confidence ``high``) —
     the Service Direct published exclusive $/lead range. ``mid`` = the geometric
     mean of the published low/high (a conservative central "average exclusive
     lead", grounded in the published numbers, not a model).
  2. **Observed exclusive average** (``service_direct_avg_2026``, ``medium``) —
     the network's 2023 blog average, CPI-adjusted to 2026, as ``mid`` with a
     spread (×0.6 / ×1.8). Used where there's no published *range* but a real
     observed price. Remodeling uses its stronger §3 CPL-tier signal instead
     (``cpl_tier``).
  3. **Cluster-sibling inheritance** (``cluster:<anchor>``, ``low``) — a
     sub-service with no vertical inherits its cluster anchor's floor (the plan's
     "HVAC's floor, not its mid" rule): ``mid`` = anchor low, ``low`` =
     0.6×anchor low, ``high`` = anchor mid. Applied only where the anchor floor
     is a *sane* value for the sub-trade; small finishing sub-trades that would be
     over-priced by inheritance keep their manual estimate instead.
  4. **Keep manual, flagged** (``manual_estimate``, ``low``) — genuine niches
     with no published price, no observed average, and no sane sibling anchor
     (moving — spec §5 has zero lead-price signal, CPC-proxy is the v2 path;
     pools, design/consulting, piano tuning, finishing sub-trades…). Never invent
     a number.

The §4 rung-2 *formula* (``CPL = job_value × close_rate × margin_share``) is kept
as ``formula_cpl`` for the market brief's monetization cross-check and for v2
(the verticals with a job value but no observed price). In v1 we anchor to
**observed** network prices wherever they exist — grounded beats modeled, and
the formula over-shoots the mid-ticket non-emergency trades (validated only for
HVAC in the spec) — so the formula is not the primary v1 anchor.

**Source of truth is the scanner's ``inputs/lead_values.csv``** (a
``market_scanner`` reload drops/recreates the table from that CSV, so the two new
columns ride on the CSV schema); the Supabase mirror-upsert in
``scripts/build_lead_values.py`` is the interim. Pure (no I/O), unit-tested in
``tests/test_leadoff_lead_values.py``.
"""
from __future__ import annotations

import math
from typing import Any

# Default margin share for the §4 CPL formula (spec §4 worked example: HVAC
# $3,401 × ~35% close × ~22% margin ≈ in-range). Calibratable — the CLI passes
# settings.leadoff_cpl_margin_share.
DEFAULT_MARGIN_SHARE = 0.22

# CPI-U cumulative inflation 2023→2026 (spec §1 "Inflation-adjusted 2023 averages").
_INFLATION_2023_TO_2026 = 1.0959


def geomean(low: float, high: float) -> float:
    """Geometric mean of a published low/high range — a conservative central
    tendency for a wide exclusive-price range (less inflated than the arithmetic
    mean, grounded in the two published endpoints)."""
    return math.sqrt(max(0.0, float(low)) * max(0.0, float(high)))


def formula_cpl(job_value: float, close_rate: float,
                margin_share: float = DEFAULT_MARGIN_SHARE) -> float:
    """The spec §4 formula: exclusive $/lead ≈ job value × close rate × margin
    share. A cross-check / monetization input in v1 (we anchor to observed
    network prices where they exist); the primary anchor for uncovered verticals
    in v2. Pure."""
    return float(job_value) * float(close_rate) * float(margin_share)


def _spread(mid: float, *, lo: float = 0.6, hi: float = 1.8) -> tuple[int, int, int]:
    return round(mid * lo), round(mid), round(mid * hi)


def _range_mid(low: float, high: float) -> tuple[int, int, int]:
    return round(low), round(geomean(low, high)), round(high)


# ── The exclusive vertical anchors (rung 1 + rung 2), from the pricing spec ────
# Each: (cpl_low, cpl_mid, cpl_high, source, confidence). Computed from the raw
# published numbers so the derivation is inspectable.

def _verticals() -> dict[str, tuple[int, int, int, str, str]]:
    # Rung 1 — Service Direct published EXCLUSIVE ranges (spec §1, bold rows).
    ranges: dict[str, tuple[float, float]] = {
        "plumbing": (60, 255),
        "hvac": (65, 325),
        "electrical": (55, 175),
        "roofing": (85, 550),
        "water_damage": (500, 2250),
        "mold": (75, 650),
        "pest": (40, 195),
        "locksmith": (15, 75),
        "appliance": (22, 85),
        "window": (30, 350),
        "door": (10, 60),
    }
    out: dict[str, tuple[int, int, int, str, str]] = {}
    for k, (lo, hi) in ranges.items():
        a, m, b = _range_mid(lo, hi)
        out[k] = (a, m, b, "service_direct_range", "high")

    # Rung 2 — observed exclusive averages (spec §1 "2026 estimate", CPI-adjusted
    # from the 2023 Service Direct blog averages). No published range, but a real
    # observed price → mid = the 2026 average, spread ×0.6 / ×1.8.
    avgs_2026 = {
        "flooring": 85, "siding": 105, "tree": 65, "gutters": 65,
        "landscaping": 45, "carpet_cleaning": 25, "handyman": 30,
    }
    for k, avg in avgs_2026.items():
        a, m, b = _spread(avg)
        out[k] = (a, m, b, "service_direct_avg_2026", "medium")

    # Remodeling: three signals (SD avg $135 [stale], §3 CPL tier $350–500,
    # OfferVault home-additions $270 wholesale floor). The CPL tier + wholesale
    # floor are the exclusive/PPL-specific signals, so anchor there, not the avg.
    out["remodeling"] = (270, 425, 550, "cpl_tier", "medium")
    return out


VERTICALS: dict[str, tuple[int, int, int, str, str]] = _verticals()

# HomeAdvisor True Cost Guide weighted job values (spec §2) + close/book rates
# (spec §3) per vertical — inputs to formula_cpl (monetization cross-check / v2).
# Not the v1 anchor; kept so the derivation is complete and testable.
JOB_VALUE: dict[str, float] = {
    "plumbing": 963, "hvac": 3401, "electrical": 602, "roofing": 7696,
    "water_damage": 6503, "mold": 1881, "remodeling": 17374, "landscaping": 2546,
    "tree": 949, "pest": 368, "locksmith": 163, "gutters": 1047,
    "flooring": 2423, "carpet_cleaning": 393, "handyman": 506, "appliance": 163,
    "window": 2768, "door": 1281, "siding": 5185,
}
CLOSE_RATE: dict[str, float] = {
    "hvac": 0.44, "plumbing": 0.43, "electrical": 0.42, "roofing": 0.44,
    "pest": 0.45, "remodeling": 0.20, "water_damage": 0.42, "_blended": 0.42,
}


# ── Category → treatment assignment (all ~105 live lead_values categories) ─────
# Exact category_name strings as stored in market_scanner.lead_values.

# Rung 1 / rung 2 direct → an exclusive vertical anchor.
_CATEGORY_VERTICAL: dict[str, str] = {
    # Electrical
    "Electrical installation service": "electrical",
    "Electrician": "electrical",
    "Lighting contractor": "electrical",
    # Flooring
    "Carpet fitter": "flooring",
    "Carpet installer": "flooring",
    "Flooring contractor": "flooring",
    "Floor refinishing service": "flooring",
    "Floor sanding and polishing service": "flooring",
    "Wood floor installation service": "flooring",
    # Handyman
    "Handyman": "handyman",
    "Home repair contractor": "handyman",
    # HVAC
    "Air conditioning contractor": "hvac",
    "Air conditioning repair service": "hvac",
    "Central heating service": "hvac",
    "Furnace repair service": "hvac",
    "Heating contractor": "hvac",
    "Hvac contractor": "hvac",
    # Carpet cleaning
    "Carpet cleaning service": "carpet_cleaning",
    # Locksmith
    "Emergency locksmith service": "locksmith",
    "Locksmith": "locksmith",
    # Pest
    "Bird control service": "pest",
    "Pest control service": "pest",
    # Plumbing
    "Drainage service": "plumbing",
    "Plumber": "plumbing",
    "Plumbing": "plumbing",
    "Septic system service": "plumbing",
    "Septic tank cleaning service": "plumbing",
    # Roofing
    "Roofing contractor": "roofing",
    "Roofing service": "roofing",
    "Skylight contractor": "roofing",
    # Water damage
    "Water damage restoration service": "water_damage",
    # Windows
    "Double glazing installer": "window",
    "Window installation service": "window",
    # Siding
    "Siding contractor": "siding",
    # Tree
    "Arborist and tree surgeon": "tree",
    "Tree service": "tree",
    # Landscaping (core)
    "Landscaper": "landscaping",
    "Landscape gardener": "landscaping",
    "Gardener": "landscaping",
    "Lawn care service": "landscaping",
    # Gutters
    "Gutter cleaning service": "gutters",
    # Appliance
    "Appliance repair service": "appliance",
    # Remodeling (full-scope remodels)
    "Bathroom remodeler": "remodeling",
    "Bathroom renovator": "remodeling",
    "General contractor": "remodeling",
    "Interior construction contractor": "remodeling",
    "Kitchen remodeler": "remodeling",
    "Kitchen renovator": "remodeling",
    "Remodeler": "remodeling",
    "Remodeller": "remodeling",
    "Renovation contractor": "remodeling",
    "Sunroom contractor": "remodeling",
}

# Rung 3 — cluster-sibling inheritance (category → anchor vertical). Applied only
# where the anchor floor is a sane value for the sub-trade (see module docstring);
# small finishing sub-trades that inheritance would over-price stay manual.
_CATEGORY_INHERIT: dict[str, str] = {
    "Air duct cleaning service": "hvac",          # plan: HVAC's floor
    "Gas engineer": "plumbing",
    "Gas installation service": "plumbing",
    "Antenna service": "electrical",
    "Home automation company": "electrical",      # plan: home automation → Electrical
    "Home cinema installation": "electrical",
    "Home theater store": "electrical",
    "Security system installer": "electrical",    # plan: security → Electrical
    "Custom home builder": "remodeling",          # plan: home builder → Remodeling-addition
    "Home builder": "remodeling",
}


def _inherit(anchor: str) -> tuple[int, int, int, str, str]:
    lo, mid, _hi, _s, _c = VERTICALS[anchor]
    return round(lo * 0.6), round(lo), round(mid), f"cluster:{anchor}", "low"


def build_lead_values(existing_rows: list[dict[str, Any]], *,
                      margin_share: float = DEFAULT_MARGIN_SHARE) -> list[dict[str, Any]]:
    """Recalibrate the lead_values rows to exclusive CPLs via the §4 ladder.

    ``existing_rows`` are the current market_scanner.lead_values rows
    (category_name, cluster, cpl_low/mid/high). Returns new rows with the same
    keys plus ``source`` + ``confidence`` — a category with no ladder match keeps
    its existing cpl values flagged ``manual_estimate`` / ``low`` (nothing
    fabricated). Sorted by (cluster, category_name) for a stable diff. Pure.

    ``margin_share`` is accepted for the formula cross-check; v1 anchors to
    observed prices, so it does not change the output rows (kept for v2 + tests).
    """
    _ = margin_share  # formula cross-check input; not the v1 anchor (see docstring)
    out: list[dict[str, Any]] = []
    for r in existing_rows:
        name = r.get("category_name")
        cluster = r.get("cluster")
        vert = _CATEGORY_VERTICAL.get(name)
        if vert is not None:
            lo, mid, hi, source, conf = VERTICALS[vert]
        elif name in _CATEGORY_INHERIT:
            lo, mid, hi, source, conf = _inherit(_CATEGORY_INHERIT[name])
        else:
            lo = r.get("cpl_low")
            mid = r.get("cpl_mid")
            hi = r.get("cpl_high")
            source, conf = "manual_estimate", "low"
        out.append({
            "category_name": name,
            "cluster": cluster,
            "cpl_low": int(lo) if lo is not None else None,
            "cpl_mid": int(mid) if mid is not None else None,
            "cpl_high": int(hi) if hi is not None else None,
            "source": source,
            "confidence": conf,
        })
    out.sort(key=lambda x: (str(x.get("cluster") or ""), str(x.get("category_name") or "")))
    return out


def diff_rows(old_rows: list[dict[str, Any]],
              new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-category before→after on the mid CPL (the board's DEFAULT_TIER), with
    the multiplier — the legible re-anchor review artifact (plan §11 acceptance
    #2). Pure; sorted by descending multiplier (biggest lifts first)."""
    old_by = {r.get("category_name"): r for r in old_rows}
    out: list[dict[str, Any]] = []
    for n in new_rows:
        o = old_by.get(n.get("category_name")) or {}
        old_mid = o.get("cpl_mid")
        new_mid = n.get("cpl_mid")
        mult = (round(new_mid / old_mid, 2)
                if old_mid not in (None, 0) and new_mid is not None else None)
        out.append({
            "category_name": n.get("category_name"),
            "cluster": n.get("cluster"),
            "old_mid": old_mid, "new_mid": new_mid, "mult": mult,
            "source": n.get("source"), "confidence": n.get("confidence"),
        })
    out.sort(key=lambda x: (x["mult"] if x["mult"] is not None else -1), reverse=True)
    return out


def summarize(new_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Coverage rollup by confidence tier (source count) — for the CLI + PR."""
    tally: dict[str, int] = {}
    for r in new_rows:
        key = str(r.get("confidence"))
        tally[key] = tally.get(key, 0) + 1
    return tally
