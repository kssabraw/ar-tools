"""LeadOff — Beatability: a single readable "how beatable is the incumbent
field?" score (0-100, higher = easier), collapsing the three field-strength
columns the board already shows — rev_win (reviews to beat #3), exact_open
(exact-category holders) and rating (avg field ★) — into one at-a-glance chip.

Reading aid ONLY — NOT a grade input. Field strength already lives inside the
scanner's rankab (→ exp_val → grade → the v3/opportunity score); scoring it again
here would double-count competitive difficulty. This module exists to make that
existing signal legible, per the owner request (2026-07-13).

Percentile-normalized against the full board distribution (34,352 markets,
measured 2026-07), so a score reads as "softer than X% of markets". Pure — no
DB/network; the distribution is baked in as interpolation breakpoints.
"""
from __future__ import annotations

from typing import Any, Optional

# (value, cumulative percentile) breakpoints from the live board distribution.
# rev_win  p25/50/75/90 = 12 / 30 / 73 / 172
# exact_open (holders)  = 2 / 7 / 16 / 29
# rating   p10/50 = 4.36 / 4.80, mean 4.72 (ratings cluster high → weak signal)
_REV_WIN_PCTL = [(0.0, 0.0), (12.0, 0.25), (30.0, 0.50), (73.0, 0.75),
                 (172.0, 0.90), (500.0, 1.0)]
_HOLDERS_PCTL = [(0.0, 0.0), (2.0, 0.25), (7.0, 0.50), (16.0, 0.75),
                 (29.0, 0.90), (80.0, 1.0)]
_RATING_PCTL = [(3.5, 0.0), (4.36, 0.10), (4.72, 0.40), (4.80, 0.50),
                (4.90, 0.72), (5.0, 1.0)]

# Weights: rev_win is the concrete, most-actionable bar; holders next; rating
# barely varies across markets so it gets the least say.
_W_REV, _W_HOLD, _W_RATING = 0.55, 0.30, 0.15

_SOFT, _MODERATE = 66, 34   # band cutoffs on the 0-100 softness scale


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _interp_pctl(value: float, points: list[tuple[float, float]]) -> float:
    """Piecewise-linear percentile rank of `value` against ascending
    (value, pctl) breakpoints, clamped to [0, 1]."""
    if value <= points[0][0]:
        return points[0][1]
    for (v0, p0), (v1, p1) in zip(points, points[1:]):
        if value <= v1:
            if v1 == v0:
                return p1
            return p0 + (p1 - p0) * (value - v0) / (v1 - v0)
    return points[-1][1]


def beatability(rev_win: Any, exact_open: Any, rating: Any) -> Optional[int]:
    """0-100 field-beatability score (higher = softer field, easier to win).
    Each present signal contributes 1 − percentile_rank(value) (low bar → high
    beatability). Missing signals drop out and the remaining weights renormalize,
    so a rating-less or holder-less row still scores off what's known. Returns
    None only when no field signal is present at all."""
    parts: list[tuple[float, float]] = []
    rv = _num(rev_win)
    if rv is not None:
        parts.append((_W_REV, 1.0 - _interp_pctl(rv, _REV_WIN_PCTL)))
    ho = _num(exact_open)
    if ho is not None:
        parts.append((_W_HOLD, 1.0 - _interp_pctl(ho, _HOLDERS_PCTL)))
    ra = _num(rating)
    if ra is not None and ra > 0:
        parts.append((_W_RATING, 1.0 - _interp_pctl(ra, _RATING_PCTL)))
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    return round(100 * sum(w * s for w, s in parts) / wsum)


def beatability_band(score: Optional[int]) -> Optional[str]:
    """soft / moderate / tough (or None when unscored)."""
    if score is None:
        return None
    return "soft" if score >= _SOFT else "moderate" if score >= _MODERATE else "tough"


def with_beatability(row: dict[str, Any]) -> dict[str, Any]:
    """Attach `beatability` + `beatability_band` to a board/brief row, read from
    its rev_win / exact_open / rating fields. Never raises."""
    score = beatability(row.get("rev_win"), row.get("exact_open"),
                        row.get("rating"))
    return {**row, "beatability": score, "beatability_band": beatability_band(score)}


def attach_beatability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map with_beatability over a list of rows."""
    return [with_beatability(r) for r in rows]
