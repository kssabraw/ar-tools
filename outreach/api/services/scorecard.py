"""The scorecard ENGINE (scoring-spec.md §1-§5). Pure arithmetic over config coefficients.

Scorecard arithmetic fails SILENTLY — a sign-flipped offset produces plausible but inverted scores
— so the golden fixtures (`tests/fixtures/golden-fixtures.json`, hand-computed BEFORE this code
existed) are the load-bearing check. If this code disagrees with them, this code is wrong; never
regenerate the fixtures from the implementation (CLAUDE.md trap).

Formula (scoring-spec §1, §5):
    raw_points       = sum of the prior integer points for the active bins
    effective_points = raw_points x lambda_shrink          (shrink the SUM, not per-bin: §5)
    score            = TargetScore + effective_points
    odds             = exp((score - offset) / factor)
    predicted_prob   = odds / (1 + odds)

`score_factors` is replayable two equivalent ways, both pinned by tests:
    TargetScore + lambda_shrink x sum(points)        == score
    TargetScore + sum(points_effective)              == score      (acceptance §1, literal form)

Model C (`value`) is NOT a scorecard: value = p_reply x p_close, and under flat pricing E[revenue]
= value x R_base x T_base ranks identically (scoring-spec §4). Its `score_factors` records the
composition, not a point sum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from api.services.scorecard_config import ScorecardParams


@dataclass(frozen=True)
class ScoreResult:
    model: str
    channel: str
    raw_points: float
    effective_points: float
    score: float
    offset: float | None
    predicted_prob: float | None
    score_factors: list[dict]


def _factor_entry(bin_name: str, params: ScorecardParams, evidence_ref: str | None) -> dict:
    meta = params.meta[bin_name]
    points = params.points_for(bin_name)
    beta = meta.get("beta")
    entry: dict = {
        "feature": meta.get("group") or bin_name,
        "bin": bin_name,
        "points": points,
        "points_effective": round(points * params.lambda_shrink, 6),
        "beta_prior": beta,
        "beta_effective": round(beta * params.lambda_shrink, 6) if beta is not None else None,
        "status": meta.get("status", "active"),
        "evidence_ref": evidence_ref,
    }
    if meta.get("unknown"):
        entry["unknown"] = True
    return entry


def score_model(
    bins: list[str],
    *,
    channel: str,
    model: str,
    params: ScorecardParams,
    evidence: dict[str, str] | None = None,
) -> ScoreResult:
    """Score one scorecard model (`reply` or `close`) for one prospect.

    `bins` is the selected bin per feature group plus any independent flags. `evidence` optionally
    maps a bin name to the DB reference that justified it (stored in score_factors.evidence_ref).
    A bin that does not belong to `model` is a programming error and raises — the extraction layer,
    not the engine, chooses bins, and a phone bin scored against the close model would be a silent
    miscalibration otherwise.
    """
    if model not in ("reply", "close"):
        raise ValueError(f"score_model handles reply/close only, not {model!r}; use compose_value")
    evidence = evidence or {}
    factors: list[dict] = []
    raw_points = 0.0
    for bin_name in bins:
        meta = params.meta.get(bin_name)
        if meta is None:
            raise KeyError(f"unknown scorecard bin {bin_name!r}")
        if meta["model"] != model:
            raise ValueError(
                f"bin {bin_name!r} belongs to model {meta['model']!r}, not {model!r}"
            )
        raw_points += params.points_for(bin_name)
        factors.append(_factor_entry(bin_name, params, evidence.get(bin_name)))

    effective_points = raw_points * params.lambda_shrink
    score = params.target + effective_points
    offset = params.offset_for(model, channel)
    prob = probability(score, offset, params.factor) if offset is not None else None
    return ScoreResult(
        model=model,
        channel=channel,
        raw_points=raw_points,
        effective_points=effective_points,
        score=score,
        offset=offset,
        predicted_prob=prob,
        score_factors=factors,
    )


def probability_from_logodds(z: float) -> float:
    """Numerically-stable logistic sigmoid(z). Shared by the score->prob and calibration paths."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def probability(score: float, offset: float, factor: float) -> float:
    """Inverse scaling (scoring-spec §4): odds = exp((score - offset)/factor); p = odds/(1+odds)."""
    return probability_from_logodds((score - offset) / factor)


def logit(prob: float) -> float:
    """ln(p / (1-p)), guarded away from 0/1 so an extreme model probability stays finite."""
    p = min(max(prob, 1e-12), 1.0 - 1e-12)
    return math.log(p / (1.0 - p))


def apply_calibration(prior_prob: float, alpha: float, gamma: float) -> float:
    """scoring-spec §6 Stage 2: ln(odds_calibrated) = alpha + gamma x ln(odds_prior).

    A monotone transform of the score (gamma > 0), so it CANNOT change rank order — it only corrects
    the probability layer. The identity (alpha=0, gamma=1) returns the input unchanged.
    """
    return probability_from_logodds(alpha + gamma * logit(prior_prob))


def display_prob(prob: float | None, calibration_alpha: float | None, clamp_pct: float) -> float | None:
    """scoring-spec §5: v1 scores are ordinal only. Clamp displayed probability to `clamp_pct`%
    until the run has a calibration_alpha (Stage 2). Never clamps the STORED predicted_prob."""
    if prob is None:
        return None
    if calibration_alpha is not None:
        return prob
    return min(prob, clamp_pct / 100.0)


@dataclass(frozen=True)
class ValueResult:
    channel: str
    raw_points: float
    score: float
    predicted_prob: float
    score_factors: list[dict]


def compose_value(
    p_reply: float,
    p_close: float,
    *,
    channel: str,
    params: ScorecardParams,
) -> ValueResult:
    """Model C (scoring-spec §4). value_prob = p_reply x p_close; E[revenue] = value_prob x R x T.

    Under flat pricing R and T are constants, so E[revenue] ranks identically to p_reply x p_close
    (§4 — the value dimension does no work while pricing is flat; do not tune R/T). Stored so the
    ranking has a dollar figure and reactivating the value layer is a config change, not a rebuild.
    """
    value_prob = p_reply * p_close
    e_revenue = value_prob * params.r_base * params.t_base
    factors = [{
        "feature": "composition",
        "kind": "composition",
        "p_reply": p_reply,
        "p_close": p_close,
        "r_base": params.r_base,
        "t_base": params.t_base,
        "note": "value = p_reply x p_close x R_base x T_base; flat pricing makes R,T constant (spec §4)",
    }]
    return ValueResult(
        channel=channel,
        raw_points=0.0,
        score=e_revenue,
        predicted_prob=value_prob,
        score_factors=factors,
    )


def replay_score(score_factors: list[dict], *, lambda_shrink: float, target: float) -> float:
    """Reproduce a scorecard score from its `score_factors` alone (acceptance §1).

    Both forms are asserted equal by the golden harness:
        target + lambda_shrink x sum(points)  ==  target + sum(points_effective)  ==  score
    A composition (value) row has no `points`; replay is defined for scorecard models only.
    """
    total = 0.0
    for f in score_factors:
        if "points" not in f:
            raise ValueError("replay_score is for scorecard models; value rows have no points")
        total += float(f["points"])
    return target + lambda_shrink * total


def validate_selection(bins: list[str], *, model: str, params: ScorecardParams) -> None:
    """Safety net for the extraction layer: no two bins from one exclusive group, all bins in-model.

    The engine's `score_model` sums whatever it is given; this catches a extraction bug where two
    mutually-exclusive bins (e.g. geogrid_lt20_steep AND geogrid_50_80) are both selected, which
    would double-count. Independent flags (group None) are exempt — they co-occur by design.
    """
    seen_groups: dict[str, str] = {}
    for bin_name in bins:
        meta = params.meta.get(bin_name)
        if meta is None:
            raise KeyError(f"unknown scorecard bin {bin_name!r}")
        if meta["model"] != model:
            raise ValueError(f"bin {bin_name!r} is model {meta['model']!r}, not {model!r}")
        group = meta.get("group")
        if group is None:
            continue
        if group in seen_groups:
            raise ValueError(
                f"bins {seen_groups[group]!r} and {bin_name!r} are both in exclusive group "
                f"{group!r} — extraction must pick one"
            )
        seen_groups[group] = bin_name
