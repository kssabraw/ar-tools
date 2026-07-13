"""LeadOff score enrichment — today's context signals promoted to sabermetric
grade inputs (owner ruling 2026-07-12: "add to the scoring rubric").

The A+…F grade was Demand × Winnability → Value → national percentile. This
layer adjusts two of those pillars with the signals we now capture, as
bounded, config-weighted multipliers:

  Winnability (× rankability):
    + proximity opportunity   (undefended geographic zones → easier)
    − incumbent site size     (big authoritative sites → harder)
    − incumbent brand strength(established brands are sticky → harder)
    ± peer-cohort field       (field weaker/stronger than comparable-size,
                               comparable-income cities → easier/harder)
  Demand (× regressed demand):
    + permit pipeline         (future customers)
    + seasonal trajectory     (real same-month YoY demand direction)

**Deliberately conservative priors** — no single signal can flip a grade
alone (winnability swings ≤ ~13%, demand ≤ ~8%); a market that is undefended
AND has weak incumbents AND rising demand earns a real, compounding bump.
Weights live in config so the calibration loop can TUNE them from real
outcomes (leadoff-calibration-plan): these are starting coefficients, not
truths. Every enriched row keeps its `base_*` (pre-enrichment) grade so each
adjustment is inspectable even though the enriched grade is now primary.

A signal that is absent for a market contributes 0 (graceful degradation) —
so a board market with only permit data is adjusted by permits alone, and a
fully-scouted market gets all four. NAP is intentionally excluded (too sparse
from the Content Analysis source to weight — see the footprint build notes).

Pure (no I/O). Unit-tested in tests/test_leadoff_scoring.py.
"""
from __future__ import annotations

import math
from typing import Any, Optional


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ── Signal normalizers → a 0-1 (or -1..1) magnitude the weights scale ─────────

def site_pressure(median_pages: Optional[float]) -> float:
    """Incumbent site size → 0-1 difficulty. Log curve (page counts are
    heavy-tailed): ~1,000 indexed pages saturates to 1.0, 100→~0.67, 10→~0.33."""
    if not median_pages or median_pages <= 0:
        return 0.0
    return _clamp(math.log10(median_pages) / 3.0, 0.0, 1.0)


def brand_pressure(median_mentions: Optional[float]) -> float:
    """Incumbent brand strength → 0-1 difficulty. Log curve: ~10,000 web
    mentions saturates to 1.0 (a 1,478-mention brand ≈ 0.79)."""
    if not median_mentions or median_mentions <= 0:
        return 0.0
    return _clamp(math.log10(median_mentions) / 4.0, 0.0, 1.0)


def permit_signal(permit_flag: Optional[str]) -> float:
    """Housing-pipeline flag → -1..1 demand tailwind. HOT-pipeline is future
    customers; COLD-pipeline is a shrinking base. Unflagged markets = 0."""
    return {"HOT-pipeline": 1.0, "COLD-pipeline": -1.0}.get(permit_flag or "", 0.0)


def seasonal_signal(growth_yoy_ss: Optional[float]) -> float:
    """Same-month YoY demand ratio → -1..1 trajectory. 1.0 = flat → 0; +50%
    (1.5) → +1, −50% (0.5) → −1. Uses the seasonality-cancelled ratio only —
    the legacy growth_yoy is too confounded to grade on."""
    if growth_yoy_ss is None:
        return 0.0
    return _clamp((float(growth_yoy_ss) - 1.0) * 2.0, -1.0, 1.0)


# ── Pillar multipliers ────────────────────────────────────────────────────────

def winnability_factor(proximity: Optional[float], site_p: Optional[float],
                       brand_p: Optional[float], w: dict[str, float],
                       peer_field: Optional[float] = None) -> float:
    return (1.0 + w["prox"] * (proximity or 0.0)
            - w["site"] * (site_p or 0.0) - w["brand"] * (brand_p or 0.0)
            + w.get("peer", 0.0) * (peer_field or 0.0))


def demand_factor(permit_s: Optional[float], season_s: Optional[float],
                  w: dict[str, float]) -> float:
    return 1.0 + w["permit"] * (permit_s or 0.0) + w["season"] * (season_s or 0.0)


def default_weights() -> dict[str, float]:
    from config import settings
    return {
        "prox": settings.leadoff_score_w_proximity,
        "site": settings.leadoff_score_w_site,
        "brand": settings.leadoff_score_w_brand,
        "permit": settings.leadoff_score_w_permit,
        "season": settings.leadoff_score_w_seasonal,
        "peer": settings.leadoff_score_w_peer_cohort,
    }


def enrich_grade(row: dict[str, Any], signals: dict[str, Any], *,
                 capture: float, lead_value: Optional[float],
                 breakpoints: list[float],
                 w: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Re-derive the grade with the enrichment multipliers applied to
    rankability + demand. `signals` carries the normalized magnitudes
    (proximity 0-1, site_pressure 0-1, brand_pressure 0-1, permit -1..1,
    seasonal -1..1 — any may be None). Preserves base_* for inspection.

    Pure — mirrors leadoff.recompute_economics so board/brief share one math."""
    from services.leadoff import grade_for, percentile_of

    w = w or default_weights()
    base_rankab = float(row.get("rankab") or 0.0)
    base_xdem = float(row.get("xdem") or 0.0)
    rev_win = float(row.get("rev_win") or 0.0)

    wf = winnability_factor(signals.get("proximity"), signals.get("site_pressure"),
                            signals.get("brand_pressure"), w,
                            peer_field=signals.get("peer_field"))
    df = demand_factor(signals.get("permit"), signals.get("seasonal"), w)
    adj_rankab = _clamp(base_rankab * wf, 0.01, 1.0)
    adj_xdem = max(0.0, base_xdem * df)

    def _econ(xdem: float, rankab: float) -> tuple[int, str]:
        lds = xdem * capture
        val = lds * lead_value if lead_value is not None else None
        ev = round(val * rankab) if val is not None else 0
        g, _ = grade_for(percentile_of(ev, breakpoints), lds, rankab, lead_value)
        return ev, g

    # base_* = the SAME assumptions with factors off, so base-vs-enriched
    # isolates the enrichment effect (not a lead-value/capture difference)
    base_exp_val, base_grade = _econ(base_xdem, base_rankab)
    leads = adj_xdem * capture
    value = leads * lead_value if lead_value is not None else None
    exp_val = round(value * adj_rankab) if value is not None else 0
    grade, build = grade_for(percentile_of(exp_val, breakpoints), leads,
                             adj_rankab, lead_value)
    # Fold the same enrichment into the scanner's v3 opportunity score so the
    # gem ranking is signal-aware, not just the grade. v3 already blends
    # demand-vs-competition; the four factors (proximity / site / brand /
    # permit / seasonal) are orthogonal dimensions it never saw, so the pillar
    # multipliers layer in without double-counting. base_v3 kept for inspection.
    base_v3 = float(row.get("v3") or 0.0)
    opportunity_v3 = round(max(0.0, base_v3 * wf * df), 1)

    present = {k: (round(v, 3) if isinstance(v, (int, float)) else v)
               for k, v in signals.items() if v is not None}
    return {
        **row,
        "base_grade": base_grade,
        "base_exp_val": base_exp_val,
        "base_v3": round(base_v3, 1),
        "opportunity_v3": opportunity_v3,
        "base_rankab": round(base_rankab, 3),
        "rankab": round(adj_rankab, 3),
        "xdem": round(adj_xdem),
        "est_leads_mo": round(leads),
        "exp_leads_mo": round(leads * adj_rankab),
        "value_mo": round(value) if value is not None else None,
        "exp_val": exp_val,
        "roi": round(exp_val / max(rev_win, 10), 1),
        "grade": grade,
        "build": build,
        "enriched": bool(present),
        "score_factors": {"winnability": round(wf, 3), "demand": round(df, 3),
                          "signals": present},
    }


def brief_signals(row: dict[str, Any], competitors: list[dict[str, Any]],
                  proximity_opportunity: Optional[float],
                  growth_yoy_ss: Optional[float],
                  peer_field: Optional[float] = None) -> dict[str, Any]:
    """Assemble the normalized signal magnitudes for one market from the pieces
    the brief already holds. Pure. Medians over whatever footprint the
    competitor rows carry (missing → that signal is None). `peer_field` is the
    precomputed peer-cohort field-strength signal read from the signal cache
    (its board-wide cohort math can't be recomputed per-brief cheaply)."""
    def _median(vals: list[float]) -> Optional[float]:
        vs = sorted(v for v in vals if v is not None)
        if not vs:
            return None
        n = len(vs)
        return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2

    pages = _median([c.get("site_pages") for c in competitors])
    mentions = _median([c.get("mentions") for c in competitors])
    return {
        "proximity": proximity_opportunity,
        "site_pressure": site_pressure(pages) if pages is not None else None,
        "brand_pressure": brand_pressure(mentions) if mentions is not None else None,
        "permit": (permit_signal(row.get("permit_flag"))
                   if row.get("permit_flag") else None),
        "seasonal": (seasonal_signal(growth_yoy_ss)
                     if growth_yoy_ss is not None else None),
        "peer_field": peer_field,
    }
