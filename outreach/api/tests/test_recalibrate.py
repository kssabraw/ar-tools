"""Stage-2 recalibration tests (scoring-spec §6). The FIT is pure and testable without real data;
the I/O (`run_recalibration`) is empty-safe and exercised live during the session (0 outcomes today).
"""

from __future__ import annotations

import math

import pytest

from api.config import Settings
from api.services import recalibrate, scorecard, scorecard_config as sc
from api.services import scoring, score_features as sf

PARAMS = sc.load_params(Settings())
TH = Settings()


def _synthetic(alpha: float, gamma: float, *, per_point: int = 300) -> tuple[list[float], list[int]]:
    """Deterministic grouped Bernoulli data drawn from sigmoid(alpha + gamma x). No RNG."""
    x: list[float] = []
    y: list[int] = []
    steps = 21
    for i in range(steps):
        xi = -4.0 + 8.0 * i / (steps - 1)
        p = scorecard.probability_from_logodds(alpha + gamma * xi)
        ones = round(p * per_point)
        for _ in range(ones):
            x.append(xi)
            y.append(1)
        for _ in range(per_point - ones):
            x.append(xi)
            y.append(0)
    return x, y


def test_fit_recovers_known_parameters():
    x, y = _synthetic(0.3, 1.2)
    alpha, gamma = recalibrate.fit_calibration(x, y)
    assert alpha == pytest.approx(0.3, abs=0.12)
    assert gamma == pytest.approx(1.2, abs=0.12)


def test_fit_of_well_calibrated_data_is_near_identity():
    # If the prior IS the truth (alpha=0, gamma=1), the fit should not move it much.
    x, y = _synthetic(0.0, 1.0)
    alpha, gamma = recalibrate.fit_calibration(x, y)
    assert alpha == pytest.approx(0.0, abs=0.12)
    assert gamma == pytest.approx(1.0, abs=0.12)


def test_fit_is_stable_on_degenerate_input():
    # No variance in x (all same prior) -> singular Hessian -> returns a stable estimate, no crash.
    alpha, gamma = recalibrate.fit_calibration([0.0] * 10, [1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
    assert math.isfinite(alpha) and math.isfinite(gamma)


def test_apply_calibration_identity_and_monotone():
    assert scorecard.apply_calibration(0.3, 0.0, 1.0) == pytest.approx(0.3, abs=1e-9)
    # gamma > 0 preserves order (rank order cannot change).
    lo = scorecard.apply_calibration(0.2, -0.5, 0.8)
    hi = scorecard.apply_calibration(0.6, -0.5, 0.8)
    assert hi > lo


def test_calibration_preserves_score_and_decile_changes_only_prob():
    inputs = sf.FeatureInputs(coverage_pct=8.0, rating=4.0, franchise_status="unknown")
    base = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                             evidence_age_days=0, prospect_id="p")
    calibrated = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS,
                                   thresholds=TH, evidence_age_days=0, prospect_id="p",
                                   reply_calibration=(0.5, 0.8))
    # Score and raw points are untouched (calibration is a probability-layer correction).
    assert calibrated.reply.score == base.reply.score
    assert calibrated.reply.raw_points == base.reply.raw_points
    # Probability changed, and value cascaded from the calibrated reply prob.
    assert calibrated.reply.predicted_prob != base.reply.predicted_prob
    assert calibrated.value.predicted_prob == pytest.approx(
        calibrated.reply.predicted_prob * calibrated.close.predicted_prob, abs=1e-9
    )


def test_identity_calibration_leaves_scores_unchanged():
    inputs = sf.FeatureInputs(coverage_pct=8.0, rating=4.0)
    base = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                             evidence_age_days=0, prospect_id="p")
    ident = scoring.score_one(inputs, channel="phone", pass_number=1, params=PARAMS, thresholds=TH,
                              evidence_age_days=0, prospect_id="p", reply_calibration=(0.0, 1.0))
    assert ident.reply.predicted_prob == pytest.approx(base.reply.predicted_prob, abs=1e-12)
