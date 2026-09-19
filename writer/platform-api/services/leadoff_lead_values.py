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
  3.5 **Observed HomeAdvisor lead-cost range** (``homeadvisor_lead_range``,
     ``medium``) — a previously-manual category whose GENUINE trade carries a
     published Service Direct resale range in the HomeAdvisor CSV (Fence → $55–175,
     Solar → $100). ``mid`` = geomean(low, high). Requires ``homeadvisor_rows``.
  3.6 **HomeAdvisor job-value formula** (``job_value_formula``, ``low``) — a
     previously-manual *project* trade with no observed price but a real job value
     in the CSV. ``CPL = weighted_job_value × close_rate × margin_share`` clamped
     to ``[FORMULA_CPL_FLOOR, FORMULA_CPL_CAP]`` (the cap is the load-bearing
     guardrail — the formula over-shoots high-ticket trades, so a $40k pool and a
     $10k cabinet both cap at the observed local-project ceiling). Requires
     ``homeadvisor_rows``; mapped conservatively (see ``_CATEGORY_JOB_MATCH``).
  4. **Keep manual, flagged** (``manual_estimate``, ``low``) — genuine niches
     with no published price, no observed average, no sane sibling anchor, and no
     HomeAdvisor job-value mapping (moving — spec §5 has zero lead-price signal,
     CPC-proxy is the v2 path; piano tuning, furniture repair, upholstery, ponds,
     fountains, sprinklers, snow removal…). Never invent a number.

Rungs 3.5/3.6 run only when ``homeadvisor_rows`` is passed; without it the ladder
is byte-identical to the observed-price-only v1 (no behaviour change). The §4
formula (``formula_cpl``) also stays available as the market brief's monetization
cross-check; the rung-1/2 observed anchors remain published prices, never modelled.

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

# ── The HomeAdvisor formula rung (valuation "full rung", built 2026-09-19) ──────
# For a currently-manual category with NO observed resale price but a real
# HomeAdvisor True Cost Guide job value (the raw 713-row
# ``homeadvisor_true_cost_guide_full.csv``), the §4 formula gives a grounded, low-
# confidence CPL estimate — better than a hand-guess: ``CPL = weighted_job_value ×
# close_rate × margin_share``, clamped to [floor, cap]. All three knobs are
# config-calibratable (``leadoff_cpl_margin_share`` / ``_formula_close_rate`` /
# ``_formula_cpl_cap`` / ``_formula_cpl_floor``).
#
# The blended book/close rate (spec §3 SearchLight, all trades ~42%). One uniform
# knob rather than per-trade rates — the cap does the heavy lifting on the high
# end, and the owner tunes close/margin/cap from the printed before→after.
FORMULA_CLOSE_RATE = 0.42
# The CAP is the empirical CPL ceiling for high-ticket local *project* trades:
# the observed Service Direct / GC-remodel lead range tops out at ~$150 (spec §1),
# and CPL **decouples from job value at the top** — roofing's $7,696 job resells
# at $85–550, not thousands. So a $40k pool job and a $10k cabinet job both cap
# here (conservative — understates the truly big-ticket ones rather than inventing
# a four-figure CPL), while mid/low-ticket trades differentiate below it.
FORMULA_CPL_CAP = 150
# Floor so a low-ticket recurring trade (cleaning) doesn't collapse to a few $.
FORMULA_CPL_FLOOR = 20


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


# ── Rung: observed HomeAdvisor lead-cost range (medium) ────────────────────────
# A currently-manual category whose GENUINE trade carries a Service Direct resale
# range in the HomeAdvisor CSV (``industry`` → lead_cost_low/high). Only these two
# manual categories have a real, same-trade observed price; the ``industry`` on a
# cross-mapped row (e.g. a chimney page filed under HVAC) is NOT that trade's price
# and is deliberately not used here.
_CATEGORY_OBSERVED: dict[str, str] = {
    "Fence contractor": "Fencing",
    "Solar energy contractor": "Solar",
}

# ── Rung: HomeAdvisor job-value formula (low) ──────────────────────────────────
# A currently-manual category → the url-slug substrings that select its
# representative HomeAdvisor sub-job cost pages. The weighted job value of the
# matched rows (samples>0) feeds the §4 formula. Only unambiguous, genuine
# project-lead trades are mapped; recurring/no-signal trades (moving — spec §5
# gap, piano tuning, furniture repair, upholstery, ponds, fountains, sprinklers,
# snow removal) are intentionally absent → they keep their flagged manual estimate
# (nothing fabricated). Matching is on the stable url path, not the title.
_CATEGORY_JOB_MATCH: dict[str, list[str]] = {
    "Asphalt contractor": ["asphalt-driveway", "tar-and-chip-driveway",
                            "driveway-repaving", "resurface-an-asphalt-driveway"],
    "Paving contractor": ["driveway-paving", "install-a-driveway",
                          "install-driveway-pavers", "install-a-concrete-driveway"],
    "Awning supplier": ["/awning"],
    "Cabinet maker": ["cabinet-installation", "custom-cabinets",
                      "cabinet-refacing", "cabinet-refinishing"],
    "Countertop contractor": ["countertop"],
    "Marble contractor": ["marble-countertops"],
    # "Tile contractor" is deliberately NOT mapped: the CSV's only tile pages are
    # grout/repair (a tile INSTALLER's job value is flooring-class, not captured),
    # so a formula off them under-values it — it keeps its flagged manual estimate.
    "Deck builder": ["deck-building", "deck-replacement", "composite-decking",
                     "cedar-deck", "aluminum-deck", "floating-deck"],
    "Demolition contractor": ["gut-a-house", "remove-concrete"],
    "Dry wall contractor": ["drywall"],
    "Plasterer": ["plaster"],
    "Masonry contractor": ["brick-wall", "cinder-block-wall",
                           "install-a-brick-stone-or-block-wall", "repoint",
                           "stamped-concrete-wall"],
    "Stucco contractor": ["stucco"],
    "Stair contractor": ["build-stairs-or-railings", "hardwood-stairs",
                         "stair-railing", "wrought-iron-railings",
                         "concrete-steps", "spiral-staircase"],
    "House cleaning service": ["housekeeping-services", "/apartment/",
                               "deep-cleaning-a-house", "move-out-cleaning"],
    "Window cleaning service": ["clean-windows"],
    "Pressure washing service": ["pressure-wash-driveway", "clean-a-roof",
                                 "powerwashing"],
    "Interior decorator": ["hire-an-interior-decorator-or-designer",
                           "staging-a-home"],
    "Interior designer": ["hire-an-interior-decorator-or-designer",
                          "staging-a-home"],
    "Swimming pool contractor": ["build-a-swimming-pool", "inground-pool",
                                 "fiberglass-pool"],
    "Pool cleaning service": ["maintain-a-swimming-pool", "repair-a-swimming-pool"],
    "Wallpaper installer": ["wallpaper"],
    "Building inspector": ["hire-a-home-inspector", "thermal-imaging-inspection"],
    "Building consultant": ["hire-an-engineer", "hire-a-draftsperson", "test-soil"],
    "Chimney sweep": ["clean-chimney"],
    # Chimney *services* = the common small repair/cap lead; the rare full rebuild
    # ($9k) is excluded so an n=0 outlier can't pin it to the cap.
    "Chimney services": ["chimney-repair", "install-replace-chimney-cap"],
}


def _to_float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def weighted_job_value(rows: list[dict[str, Any]]) -> float | None:
    """Sample-weighted mean HomeAdvisor job value over ``rows`` (spec §4: use the
    vertical-weighted value, not a single flagship sub-job page). Weights by
    ``job_value_sample_n`` for rows with a real sample (n>0); falls back to a plain
    mean of ``job_value_avg`` when none of the matched rows carry a sample (still a
    grounded directional). ``None`` when nothing usable. Pure."""
    weighted: list[tuple[float, float]] = []
    plain: list[float] = []
    for r in rows:
        v = _to_float(r.get("job_value_avg"))
        if v is None or v <= 0:
            continue
        plain.append(v)
        n = _to_float(r.get("job_value_sample_n"))
        if n is not None and n > 0:
            weighted.append((v, n))
    if weighted:
        tot = sum(n for _, n in weighted)
        return sum(v * n for v, n in weighted) / tot
    if plain:
        return sum(plain) / len(plain)
    return None


def match_job_rows(homeadvisor_rows: list[dict[str, Any]],
                   patterns: list[str]) -> list[dict[str, Any]]:
    """HomeAdvisor rows whose ``url`` contains any of ``patterns``. Pure."""
    return [r for r in homeadvisor_rows
            if any(p in str(r.get("url", "")) for p in patterns)]


def observed_range(industry: str,
                   homeadvisor_rows: list[dict[str, Any]]) -> tuple[int, int, int] | None:
    """The Service Direct exclusive lead-cost range published for ``industry`` in
    the HomeAdvisor CSV → (low, geomean, high). ``None`` if that industry carries
    no lead-cost figure (e.g. Garage door). Pure."""
    for r in homeadvisor_rows:
        if r.get("industry") != industry:
            continue
        lo = _to_float(r.get("lead_cost_low"))
        hi = _to_float(r.get("lead_cost_high"))
        if lo is not None and hi is not None:
            return round(lo), round(geomean(lo, hi)), round(hi)
    return None


def job_value_formula_cpl(job_value: float, *, close_rate: float = FORMULA_CLOSE_RATE,
                          margin_share: float = DEFAULT_MARGIN_SHARE,
                          cap: int = FORMULA_CPL_CAP,
                          floor: int = FORMULA_CPL_FLOOR) -> int:
    """The §4 formula CPL for one weighted job value, **clamped** to [floor, cap]
    — the rung-3.6 anchor. Wraps the raw ``formula_cpl`` cross-check. Pure. The
    clamp is the load-bearing guardrail: the raw formula over-shoots high-ticket
    trades (a $40k pool at 9% ≈ $3,600, absurd for a resale CPL), so it is capped
    at the observed local-project ceiling; the floor keeps a low-ticket recurring
    trade off a nonsense few-dollar value."""
    raw = round(formula_cpl(job_value, close_rate, margin_share))
    return max(int(floor), min(int(cap), raw))


def build_lead_values(existing_rows: list[dict[str, Any]], *,
                      margin_share: float = DEFAULT_MARGIN_SHARE,
                      homeadvisor_rows: list[dict[str, Any]] | None = None,
                      formula_close_rate: float = FORMULA_CLOSE_RATE,
                      formula_cpl_cap: int = FORMULA_CPL_CAP,
                      formula_cpl_floor: int = FORMULA_CPL_FLOOR) -> list[dict[str, Any]]:
    """Recalibrate the lead_values rows to exclusive CPLs via the §4 ladder.

    ``existing_rows`` are the current market_scanner.lead_values rows
    (category_name, cluster, cpl_low/mid/high). Returns new rows with the same
    keys plus ``source`` + ``confidence`` — a category with no ladder match keeps
    its existing cpl values flagged ``manual_estimate`` / ``low`` (nothing
    fabricated). Sorted by (cluster, category_name) for a stable diff. Pure.

    When ``homeadvisor_rows`` (the raw HomeAdvisor True Cost Guide CSV rows) is
    provided, two extra rungs run for the previously-manual categories BEFORE the
    manual fallback: an **observed lead-cost range** (medium) where the trade has a
    genuine Service Direct price (Fence, Solar), and a **job-value formula** (low)
    for the mapped project trades. When it is ``None`` these rungs are skipped, so
    the output is byte-identical to the observed-price-only ladder (existing tests
    unchanged, no behaviour change unless the CSV is passed).

    ``margin_share`` also feeds the formula rung (with ``formula_close_rate`` and
    the ``formula_cpl_cap``/``_floor`` clamp). It still does not touch the rung-1/2
    observed anchors (those are published prices, not modelled).
    """
    ha = homeadvisor_rows or []
    out: list[dict[str, Any]] = []
    for r in existing_rows:
        name = r.get("category_name")
        cluster = r.get("cluster")
        vert = _CATEGORY_VERTICAL.get(name)
        obs = observed_range(_CATEGORY_OBSERVED[name], ha) if (
            ha and name in _CATEGORY_OBSERVED) else None
        jv = weighted_job_value(match_job_rows(ha, _CATEGORY_JOB_MATCH[name])) if (
            ha and name in _CATEGORY_JOB_MATCH) else None
        if vert is not None:
            lo, mid, hi, source, conf = VERTICALS[vert]
        elif name in _CATEGORY_INHERIT:
            lo, mid, hi, source, conf = _inherit(_CATEGORY_INHERIT[name])
        elif obs is not None:
            lo, mid, hi = obs
            source, conf = "homeadvisor_lead_range", "medium"
        elif jv is not None:
            mid = job_value_formula_cpl(jv, close_rate=formula_close_rate,
                                        margin_share=margin_share,
                                        cap=formula_cpl_cap, floor=formula_cpl_floor)
            lo, hi = round(mid * 0.6), round(mid * 1.5)
            source, conf = "job_value_formula", "low"
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
