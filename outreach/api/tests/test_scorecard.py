"""The golden-fixture harness — the load-bearing check for the scorecard engine (scoring-spec §10).

`tests/fixtures/golden-fixtures.json` was hand-computed from the spec's coefficient tables BEFORE
any code existed. It is the authority: if the engine disagrees, the ENGINE is wrong. These fixtures
are never regenerated from the implementation (CLAUDE.md trap). There is no CI in this repo, so this
local run IS the check — scorecard arithmetic fails silently, and a sign-flipped offset produces
plausible-but-inverted scores that only these independent numbers catch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.config import Settings
from api.services import scorecard, scorecard_config as sc

_FIXTURES_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "golden-fixtures.json"


def _load_fixtures() -> dict:
    return json.loads(_FIXTURES_PATH.read_text())


def _params() -> sc.ScorecardParams:
    # Default settings = the elicited priors shipped in config. The fixtures were computed against
    # exactly these defaults (factor 72.1348, lambda 0.5, offsets 705/579.3/625.1).
    return sc.load_params(Settings())


FIXTURES = _load_fixtures()["fixtures"]
META = _load_fixtures()


def test_fixture_file_shape():
    assert META["factor"] == pytest.approx(72.1348, abs=1e-4)
    assert META["lambda_shrink"] == 0.5
    assert META["offsets"] == {"email": 705.0, "phone": 579.3, "close": 625.1}
    assert len(FIXTURES) == 7


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["fixture"] for f in FIXTURES])
def test_golden_fixture_scores_and_probabilities(fx):
    """Every fixture: raw_points, effective_points, score (exact 2dp), prob (0.05pp), display clamp."""
    params = _params()
    result = scorecard.score_model(
        fx["features"], channel=fx["channel"], model="reply", params=params
    )

    # raw_points and effective_points reproduce the independently-computed values exactly.
    assert result.raw_points == fx["raw_points"], fx["fixture"]
    assert result.effective_points == pytest.approx(fx["effective_points"], abs=1e-9)

    # score exact to 2dp (fixture tolerance).
    assert result.score == pytest.approx(fx["expected_score"], abs=0.005), fx["fixture"]

    # probability to 0.05pp.
    prob_pct = result.predicted_prob * 100.0
    assert prob_pct == pytest.approx(fx["expected_prob_pct"], abs=0.05), fx["fixture"]

    # displayed probability: clamped to 60% at Stage 1 (no calibration_alpha).
    displayed = scorecard.display_prob(
        result.predicted_prob, calibration_alpha=None, clamp_pct=params.display_prob_clamp_pct
    )
    assert displayed * 100.0 == pytest.approx(fx["expected_prob_displayed_pct"], abs=0.05), fx["fixture"]


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["fixture"] for f in FIXTURES])
def test_score_factors_replayable(fx):
    """Acceptance §1: score reproducible from score_factors alone, both replay forms agree."""
    params = _params()
    result = scorecard.score_model(
        fx["features"], channel=fx["channel"], model="reply", params=params
    )
    # Form 1: target + lambda x sum(points)
    replayed = scorecard.replay_score(
        result.score_factors, lambda_shrink=params.lambda_shrink, target=params.target
    )
    assert replayed == pytest.approx(result.score, abs=1e-9)
    # Form 2 (literal "sum of points + offset"): target + sum(points_effective)
    literal = params.target + sum(f["points_effective"] for f in result.score_factors)
    assert literal == pytest.approx(result.score, abs=1e-6)
    # Every active feature is represented (the fixture's feature list is fully accounted for).
    assert [f["bin"] for f in result.score_factors] == fx["features"]


def test_phone_and_email_use_different_offsets():
    """scoring-spec §1: the two channels are 126 points apart and must never share an offset."""
    params = _params()
    assert params.offset_for("reply", "email") == 705.0
    assert params.offset_for("reply", "phone") == 579.3
    assert params.offset_for("reply", "email") != params.offset_for("reply", "phone")
    assert params.offset_for("close", "phone") == params.offset_for("close", "email") == 625.1


def test_same_prospect_scores_differently_by_channel():
    """F1 and F5 are the SAME prospect on email vs phone — same-shaped features, different offset,
    genuinely different probability. Pinning that the pair is not accidentally identical."""
    params = _params()
    email = scorecard.score_model(
        FIXTURES[0]["features"], channel="email", model="reply", params=params
    )
    phone = scorecard.score_model(
        FIXTURES[4]["features"], channel="phone", model="reply", params=params
    )
    assert email.predicted_prob != phone.predicted_prob
    # Phone base rate (25%) is far above email (5.5%), so the phone reply prob is higher.
    assert phone.predicted_prob > email.predicted_prob


def test_all_unknown_lands_at_base_rate():
    """F4: an all-reference/unknown prospect scores exactly 500 and predicts the email base rate."""
    params = _params()
    result = scorecard.score_model(
        FIXTURES[3]["features"], channel="email", model="reply", params=params
    )
    assert result.score == 500.0
    assert result.raw_points == 0.0
    assert result.predicted_prob * 100.0 == pytest.approx(5.51, abs=0.05)


def test_offsets_are_consistent_with_base_rates():
    """The pinned offsets must be the derivation of the configured base rates (scoring-spec §1).

    Coarse tolerance (0.2) because the pinned values are rounded to 1dp; this catches a base rate
    changed per §9 without regenerating its offset, not floating-point noise.
    """
    params = _params()
    for base_rate, pinned in (
        (params.base_rate_reply_email, params.offset_email),
        (params.base_rate_reply_phone, params.offset_phone),
        (params.base_rate_close, params.offset_close),
    ):
        derived = sc.derive_offset(base_rate, params.factor, params.target)
        assert derived == pytest.approx(pinned, abs=0.2)


def test_probability_is_numerically_stable_at_extremes():
    params = _params()
    assert scorecard.probability(9999.0, 500.0, params.factor) == pytest.approx(1.0, abs=1e-9)
    assert scorecard.probability(-9999.0, 500.0, params.factor) == pytest.approx(0.0, abs=1e-9)


# --- config / registry -----------------------------------------------------------------------

def test_unknown_bin_raises_never_scores_zero():
    """A typo in extraction must fail loudly — an unknown bin scoring as 0 is a silent miscalibration."""
    params = _params()
    with pytest.raises(KeyError):
        params.points_for("geogrid_lt19_supersteep")
    with pytest.raises(KeyError):
        scorecard.score_model(["not_a_real_bin"], channel="phone", model="reply", params=params)


def test_bin_scored_against_wrong_model_raises():
    params = _params()
    # A close-model bin cannot be summed into a reply score.
    with pytest.raises(ValueError):
        scorecard.score_model(["close_owner_dm"], channel="phone", model="reply", params=params)


def test_json_override_changes_points_and_nothing_else():
    settings = Settings(scorecard_coefficients_json='{"geogrid_lt20_steep": 60}')
    params = sc.load_params(settings)
    assert params.points_for("geogrid_lt20_steep") == 60.0
    # Untouched bins keep their prior.
    assert params.points_for("owner_operated") == 29.0


def test_json_override_rejects_unknown_bin_and_bad_json():
    with pytest.raises(ValueError):
        sc.load_params(Settings(scorecard_coefficients_json='{"no_such_bin": 5}'))
    with pytest.raises(ValueError):
        sc.load_params(Settings(scorecard_coefficients_json="not json"))


def test_validate_selection_rejects_two_bins_from_one_group():
    params = _params()
    with pytest.raises(ValueError):
        scorecard.validate_selection(
            ["geogrid_lt20_steep", "geogrid_50_80"], model="reply", params=params
        )
    # Independent flags co-occur legally.
    scorecard.validate_selection(["ads_gap", "aw_tag", "meta_pixel"], model="reply", params=params)


def test_value_composition_ranks_by_p_reply_times_p_close():
    params = _params()
    v = scorecard.compose_value(0.30, 0.20, channel="phone", params=params)
    assert v.predicted_prob == pytest.approx(0.06, abs=1e-9)
    assert v.score == pytest.approx(0.06 * params.r_base * params.t_base, abs=1e-6)
    # Higher propensity ranks higher under flat pricing.
    v2 = scorecard.compose_value(0.40, 0.20, channel="phone", params=params)
    assert v2.score > v.score
