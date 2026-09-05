"""Missed-opportunity valuation — the dollar pain point (Phase A, PURE core).

The dollar figure a prospect forgoes by NOT ranking in the Google Maps pack, framed as a
competitive pain point. Spec: `outreach/docs/missed-opportunity-valuation-prd-v0_1.md`.

This module is the deterministic MATH only — no I/O, no config reads, no LLM. Every input is passed
in; the wiring layer (`services/outreach.py`) reads the cached demand, the coverage `rank_vector`,
the Census downscale and the config assumptions, and hands them here. Keeping it pure is what makes
the number replayable and unit-testable, the same discipline as the heatmap renderer.

The honesty rules this module encodes (they are the whole reason the number is allowed to exist in a
module whose governing invariant is *never fabricate a number*):

- It is the module's FIRST modeled number. It earns its place by SHOWING ITS WORK, not by being
  precise: it is a RANGE, every soft input is returned alongside it (`inputs`), and it carries a
  one-sentence `how_estimated` provenance line. The caller renders it as *estimated missed
  opportunity*, never "you are losing $X" (vocabulary: "missed opportunity", never "loss").
- Only the demand link is near-measured (search volume, CPC — both from a paid DataForSEO call).
  Close rate and job value are ASSUMPTIONS, so they drive the LOW→HIGH band, never a point figure.
- Two framings. **Ad-cost-equivalent** (`missed_clicks × cpc`) carries no soft assumption — CPC is
  measured and already prices a click — so it is a single defensible ANCHOR. **Missed-revenue**
  (`missed_clicks × close × job_value`) carries the two soft assumptions, so it is the BAND.
- Unknown ≡ absent: a missing input yields `available=False` with a `reason`, never a zero and never
  a guessed default. The caller then simply omits the dollar line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The local Google pack shows three results. "Missed" = a measured grid point where the prospect is
# NOT in the top `PACK_SIZE`. Config-overridable at the wiring layer, defaulted here for the pure
# helpers and their tests.
DEFAULT_PACK_SIZE = 3


# --- inputs -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryAssumptions:
    """The two soft per-vertical assumptions that drive the missed-revenue band, plus provenance.

    `source` is 'category' when the prospect's vertical matched the table, else 'global' (the
    conservative fallback for an unknown/off-category vertical — the honest behaviour, since we do
    not know an unclassifiable business's economics). `vertical` is the resolved key (or None)."""

    close_rate_low: float
    close_rate_high: float
    job_value_low: float
    job_value_high: float
    source: str = "global"           # 'category' | 'global'
    vertical: str | None = None


# --- valuation result -------------------------------------------------------------------------


@dataclass(frozen=True)
class Valuation:
    """A computed valuation, or an explained absence. Everything the surfaces render, plus every
    input that produced it (so the number shows its work and stays replayable)."""

    available: bool
    reason: str | None = None                    # why unavailable, or None

    # Ad-cost-equivalent: the defensible anchor (None when CPC is unknown).
    ad_cost_equivalent_monthly: int | None = None
    # Missed-revenue band: the emotional number, low→high from the soft assumptions
    # (None when demand/scaling is unavailable).
    missed_revenue_low_monthly: int | None = None
    missed_revenue_high_monthly: int | None = None

    # The intermediate quantities, exposed so the caller can render + audit them.
    missed_clicks_monthly: float = 0.0
    local_monthly_demand: int = 0
    missed_fraction: float = 0.0                 # share of measured grid outside the pack
    invisible_points: int = 0
    live_points: int = 0

    how_estimated: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)


# --- pure helpers -----------------------------------------------------------------------------


def pack_capture_rate_from_curve(curve: dict[str, float], pack_size: int = DEFAULT_PACK_SIZE) -> float:
    """The share of local searchers a single in-pack listing captures, from a 3-pack CTR curve.

    The counterfactual is deliberately modest — "if you were IN the pack", not "#1 everywhere" — so
    we do not know which of the pack positions the prospect would reach. The conservative, honest
    reading is the MEAN of the pack positions' click shares (you might land anywhere in the pack).
    `curve` maps position (as a string, "1".."N") to that position's click share of all searchers.
    Missing positions contribute 0. Returns 0.0 for an empty/garbage curve (→ no dollar figure,
    never a fabricated one)."""
    if pack_size <= 0:
        return 0.0
    shares: list[float] = []
    for pos in range(1, pack_size + 1):
        val = curve.get(str(pos))
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            shares.append(float(val))
    if not shares:
        return 0.0
    # Mean over the FULL pack width (missing positions count as 0 share), so a curve that only
    # defines position 1 doesn't overstate the average in-pack capture.
    return sum(shares) / float(pack_size)


def missed_fraction(live_points: int, in_pack_points: int) -> float:
    """Share of MEASURED grid points where the prospect is outside the pack.

    `live_points` is the contemporaneous coverage denominator (measured, land-masked — never
    re-derived, per the coverage invariant). `in_pack_points` is how many of those points rank the
    prospect within the pack. Clamped to [0, 1]; 0 live points → 0.0 (handled as `no_coverage`
    upstream)."""
    if live_points <= 0:
        return 0.0
    invisible = max(0, live_points - max(0, in_pack_points))
    return min(1.0, invisible / live_points)


def resolve_assumptions(
    category_text: str | None,
    table: dict[str, dict[str, float]],
    global_default: dict[str, float],
) -> CategoryAssumptions:
    """Resolve a prospect's per-vertical close-rate + job-value band from the config table.

    Keys the table on a normalised vertical derived from the prospect's Google/Outscraper category
    text (lower/trim, then a containment match against the table's keys — "Emergency plumber service"
    resolves the "plumber" vertical). An unknown/off-category vertical falls to the conservative
    `global_default` with `source='global'` — we do not invent economics for a business we could not
    classify. Never raises; a malformed table entry falls through to the global default."""
    normalised = (category_text or "").strip().lower()
    if normalised and table:
        # Prefer the longest matching key so "plumbing contractor" beats "plumber" when both are keys.
        for key in sorted(table.keys(), key=len, reverse=True):
            k = key.strip().lower()
            if not k:
                continue
            if k == normalised or k in normalised or normalised in k:
                entry = table.get(key) or {}
                assumptions = _assumptions_from(entry, source="category", vertical=key)
                if assumptions is not None:
                    return assumptions
    fallback = _assumptions_from(global_default, source="global", vertical=None)
    if fallback is not None:
        return fallback
    # A missing/garbage global default is a config error; degrade to zeros so the band is 0–0 and the
    # caller shows no missed-revenue figure, rather than raising in a read path.
    return CategoryAssumptions(0.0, 0.0, 0.0, 0.0, source="global", vertical=None)


def _assumptions_from(
    entry: dict[str, Any], *, source: str, vertical: str | None
) -> CategoryAssumptions | None:
    """Build a CategoryAssumptions from a config dict, or None if it lacks the fields. Orders the
    low/high defensively so a mis-entered table (high < low) can't invert the band."""
    try:
        close_lo = float(entry["close_rate_low"])
        close_hi = float(entry["close_rate_high"])
        job_lo = float(entry["job_value_low"])
        job_hi = float(entry["job_value_high"])
    except (KeyError, TypeError, ValueError):
        return None
    return CategoryAssumptions(
        close_rate_low=min(close_lo, close_hi),
        close_rate_high=max(close_lo, close_hi),
        job_value_low=min(job_lo, job_hi),
        job_value_high=max(job_lo, job_hi),
        source=source,
        vertical=vertical,
    )


def nice_round(value: float, step: int) -> int:
    """Round to the nearest `step` to signal that the figure is an estimate, not a measurement.

    A dollar valuation shown to the cent reads as precise, and this number is not — so ad-cost
    anchors round to a small step and the revenue band to a coarser one (set by the caller).
    Never returns a negative; 0 stays 0."""
    if step <= 0:
        return max(0, int(round(value)))
    return max(0, int(round(value / step)) * step)


def parse_ctr_curve(raw: str) -> dict[str, float]:
    """A CTR curve config string → {position: share}. Pure, guarded — a malformed/empty string
    yields {} (→ pack_capture_rate 0 → no dollar figure, never a fabricated one)."""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in data.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[str(k)] = float(v)
    return out


def parse_category_table(raw: str) -> dict[str, dict[str, float]]:
    """A per-category assumptions config string → {vertical: {close_rate_low, ...}}. Pure, guarded —
    a malformed/empty string yields {} (→ every vertical uses the global fallback)."""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def in_pack_count_from_vector(vector: list[int], pack_size: int = DEFAULT_PACK_SIZE) -> int:
    """How many grid points rank the prospect within the pack (byte 1..pack_size). Pure. A dead point
    (255) and a measured-absent point (0) are both NOT in the pack, so they never count here."""
    return sum(1 for b in (vector or []) if 1 <= int(b) <= pack_size)


def _money(n: int) -> str:
    return f"${n:,}"


def spoken_line(
    v: "Valuation", *, keyword: str | None = None, submarket: str | None = None
) -> str | None:
    """The deterministic sentence a caller reads (and the internal brief shows) for an AVAILABLE
    valuation, or None. Leads with the missed-revenue band (the punchy number, PRD Q2/Q4), then the
    ad-cost-equivalent anchor as the defensible floor, then the 'how we estimated this' line. Never
    LLM-phrased — a computed range doesn't need sharpening, and keeping it out of the LLM path keeps
    the call-hook fabrication guard intact."""
    if not v.available:
        return None
    what = f"“{keyword}” " if keyword else ""
    where = f" across {submarket}" if submarket else ""
    lo, hi = v.missed_revenue_low_monthly, v.missed_revenue_high_monthly
    if lo is not None and hi is not None and hi > 0:
        band = f"{_money(lo)}–{_money(hi)}/mo" if lo != hi else f"{_money(hi)}/mo"
        lead = (
            f"An estimated {band} of {what}work is going to competitors while this business is "
            f"missing from the map pack{where}"
        )
    elif v.ad_cost_equivalent_monthly is not None:
        lead = (
            f"The {what}map-pack demand this business is missing{where} is worth about "
            f"{_money(v.ad_cost_equivalent_monthly)}/mo"
        )
    else:
        return None
    anchor = ""
    if v.ad_cost_equivalent_monthly is not None:
        anchor = f" — about {_money(v.ad_cost_equivalent_monthly)}/mo to replace that traffic with Google Ads"
    return f"{lead}{anchor}. {v.how_estimated}"


def build_how_estimated(
    *, source: str, downscaled: bool, has_cpc: bool
) -> str:
    """The one-sentence 'how we estimated this' line that rides every surface (PRD Q1).

    States the chain plainly and names the assumptions as assumptions — never presents the number as
    measured."""
    demand = "local monthly searches for this keyword"
    if downscaled:
        demand = "this keyword's metro search volume, scaled to the local area by population"
    basis = (
        f"{demand}, the share of the map where competitors outrank this business, "
        "and typical local pack click-through"
    )
    if source == "category":
        assume = "close rate and job value typical for this trade (both assumptions you can adjust)"
    else:
        assume = "conservative close-rate and job-value assumptions you can adjust"
    tail = f" The dollar range uses {assume}." if has_cpc else f" The range uses {assume}."
    return f"Estimated from {basis}.{tail}"


# --- the computation --------------------------------------------------------------------------


def compute_valuation(
    *,
    search_volume: int | None,
    cpc: float | None,
    population_ratio: float | None,
    live_points: int,
    in_pack_points: int,
    assumptions: CategoryAssumptions,
    pack_capture_rate: float,
    demand_fetched: bool = True,
    ad_cost_round_step: int = 10,
    revenue_round_step: int = 100,
) -> Valuation:
    """Compute the estimated missed opportunity, or return an explained absence.

    The chain: `local_demand = search_volume × population_ratio`; `missed_clicks = local_demand ×
    missed_fraction × pack_capture_rate`; ad-cost-equivalent = `missed_clicks × cpc` (anchor);
    missed-revenue band = `missed_clicks × close_rate × job_value` at the low and high assumptions.

    Availability is decided by the inputs, never faked:
      - not `demand_fetched`            → reason 'not_fetched' (no keyword_demand row yet)
      - search_volume None/0            → reason 'no_demand'   (asked, no measurable volume)
      - population_ratio None           → reason 'no_local_scaling' (Census downscale unavailable)
      - live_points <= 0                → reason 'no_coverage'
      - missed_fraction == 0            → reason 'not_missing'  (in the pack everywhere measured)
    A missing CPC does NOT make the whole thing unavailable — it only drops the ad-cost anchor;
    the missed-revenue band still computes.
    """
    live = max(0, int(live_points))
    in_pack = max(0, int(in_pack_points))
    frac = missed_fraction(live, in_pack)
    invisible = max(0, live - min(in_pack, live))

    inputs: dict[str, Any] = {
        "search_volume": search_volume,
        "cpc": cpc,
        "population_ratio": population_ratio,
        "live_points": live,
        "in_pack_points": min(in_pack, live),
        "invisible_points": invisible,
        "pack_capture_rate": pack_capture_rate,
        "close_rate_low": assumptions.close_rate_low,
        "close_rate_high": assumptions.close_rate_high,
        "job_value_low": assumptions.job_value_low,
        "job_value_high": assumptions.job_value_high,
        "assumptions_source": assumptions.source,
        "vertical": assumptions.vertical,
    }

    def _unavailable(reason: str) -> Valuation:
        return Valuation(
            available=False,
            reason=reason,
            missed_fraction=frac,
            invisible_points=invisible,
            live_points=live,
            inputs=inputs,
        )

    if not demand_fetched:
        return _unavailable("not_fetched")
    if not search_volume or search_volume <= 0:
        return _unavailable("no_demand")
    if population_ratio is None or population_ratio <= 0:
        return _unavailable("no_local_scaling")
    if live <= 0:
        return _unavailable("no_coverage")
    if frac <= 0:
        return _unavailable("not_missing")

    local_demand = float(search_volume) * float(population_ratio)
    missed_clicks = local_demand * frac * max(0.0, pack_capture_rate)

    ad_cost: int | None = None
    has_cpc = cpc is not None and cpc > 0
    if has_cpc:
        ad_cost = nice_round(missed_clicks * float(cpc), ad_cost_round_step)

    rev_low = nice_round(
        missed_clicks * assumptions.close_rate_low * assumptions.job_value_low, revenue_round_step
    )
    rev_high = nice_round(
        missed_clicks * assumptions.close_rate_high * assumptions.job_value_high, revenue_round_step
    )

    return Valuation(
        available=True,
        reason=None,
        ad_cost_equivalent_monthly=ad_cost,
        missed_revenue_low_monthly=rev_low,
        missed_revenue_high_monthly=rev_high,
        missed_clicks_monthly=missed_clicks,
        local_monthly_demand=int(round(local_demand)),
        missed_fraction=frac,
        invisible_points=invisible,
        live_points=live,
        how_estimated=build_how_estimated(
            source=assumptions.source,
            downscaled=(population_ratio is not None and population_ratio < 1.0),
            has_cpc=has_cpc,
        ),
        inputs=inputs,
    )
