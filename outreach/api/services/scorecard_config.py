"""The scoring model's coefficient REGISTRY and scaling parameters (scoring-spec.md §1-§4).

This module is the single config source for every coefficient in the Phase-4 scorecard. The
scalar knobs (PDO, target, lambda_shrink, offsets, base rates) come from `api.config.Settings`;
the ~40 elicited-prior point values live in `COEFFICIENTS` below and are overridable per bin via
`OUTREACH_SCORECARD_COEFFICIENTS_JSON`. Nothing in the scoring LOGIC (`scorecard.py`) hardcodes a
beta — it reads points from `ScorecardParams`, which this module assembles. That is the
"all coefficients load from config, zero hardcoded betas" invariant, made structural.

THE POINTS ARE AUTHORITATIVE, NOT THE DISPLAYED BETAS. The spec's integer point columns were
computed from full-precision ln(OR), so `round(displayed_beta x factor)` does NOT always reproduce
them (e.g. owner_operated: ln(1.5)=0.4055 -> +29, but round(0.41 x 72.13)=30). The golden fixtures
were hand-computed from the INTEGER points, so those integers are what is transcribed here and what
the engine sums. `or`/`beta` are carried for the `score_factors` audit trail only.

Every value is an ELICITED estimate. No coefficient has been tested against a single reply. Rank
order is a strong prior, not a prediction, until ~100 prospects have been contacted (CLAUDE.md).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field


def factor_of(pdo: float) -> float:
    """scoring-spec §1: Factor = PDO / ln(2). Derived, never stored — pdo is the only knob."""
    return pdo / math.log(2)


def derive_offset(base_rate: float, factor: float, target: float) -> float:
    """scoring-spec §1: Offset = TargetScore - Factor x ln(TargetOdds), TargetOdds = p/(1-p).

    The relationship between a base rate and its offset. The offsets shipped in Settings are PINNED
    to the golden fixtures; a unit test asserts this derivation rounds to them, so changing a base
    rate per §9 without regenerating its offset fails loudly rather than miscalibrating in silence.
    """
    odds = base_rate / (1.0 - base_rate)
    return target - factor * math.log(odds)


# ---------------------------------------------------------------------------------------------
# THE COEFFICIENT REGISTRY. Flat by bin name (names are unique across models; close/value bins are
# namespaced `close_`). Each bin carries:
#   points          — the spec's integer point value. AUTHORITATIVE. What the engine sums.
#   or, beta        — the elicited odds ratio and ln(OR). Audit trail only (score_factors).
#   model           — 'reply' | 'close'. A score for a model only accepts that model's bins.
#   group           — the mutually-exclusive feature group this bin belongs to, or None for an
#                     independent additive flag (buying-intent / organic-AI pain — these co-occur).
#   channel         — 'email' | 'phone' | None. Set only on reachability bins, which are
#                     channel-specific (scoring-spec §2 Reachability).
#   ref             — True if this is the 0-point reference bin of its group.
#   unknown         — True if this bin means "not measurable yet" (0 points, flagged, never absent).
#   status          — 'active' | 'unavailable'. 'unavailable' bins (case studies AR does not hold)
#                     score for nobody and shift every prospect equally, so ranking is unaffected;
#                     they activate with no coefficient change when the asset exists (§Case-study).
# ---------------------------------------------------------------------------------------------

_R = {"ref": True}
_U = {"unknown": True}

COEFFICIENTS: dict[str, dict] = {
    # --- Model A (reply) -------------------------------------------------------------------
    # Reachability — channel-specific. The two tracks MUST NOT be ranked together (§2).
    "reach_email_direct": {"points": 66, "or": 2.5, "beta": 0.92, "model": "reply",
                           "group": "reachability_email", "channel": "email"},
    "reach_email_role": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply",
                         "group": "reachability_email", "channel": "email", **_R},
    "reach_email_phone_only": {"points": -66, "or": 0.4, "beta": -0.92, "model": "reply",
                               "group": "reachability_email", "channel": "email"},
    "reach_phone_direct_owner": {"points": 50, "or": 2.0, "beta": 0.69, "model": "reply",
                                 "group": "reachability_phone", "channel": "phone"},
    "reach_phone_listed": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply",
                           "group": "reachability_phone", "channel": "phone", **_R},
    "reach_phone_gatekept": {"points": -37, "or": 0.6, "beta": -0.51, "model": "reply",
                             "group": "reachability_phone", "channel": "phone"},

    # Change signals (delta since prior scan). All resolve to `delta_first_scan` (0, unknown) on a
    # submarket's first scan — absence of a baseline is not evidence of stability (§2).
    "delta_lost_pack_15pp": {"points": 63, "or": 2.4, "beta": 0.88, "model": "reply",
                             "group": "change_signal"},
    "delta_competitor_overtook": {"points": 57, "or": 2.2, "beta": 0.79, "model": "reply",
                                  "group": "change_signal"},
    "delta_ads_newly_on": {"points": 46, "or": 1.9, "beta": 0.64, "model": "reply",
                           "group": "change_signal"},
    "delta_dropped_ai": {"points": 38, "or": 1.7, "beta": 0.53, "model": "reply",
                         "group": "change_signal"},
    "delta_organic_lost5": {"points": 29, "or": 1.5, "beta": 0.41, "model": "reply",
                            "group": "change_signal"},
    "delta_velocity_stalled": {"points": 24, "or": 1.4, "beta": 0.34, "model": "reply",
                               "group": "change_signal"},
    "delta_none": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply",
                   "group": "change_signal", **_R},
    "delta_first_scan": {"points": 0, "model": "reply", "group": "change_signal", **_U},

    # Vendor-failing (compound — highest-intent, needs two scan cycles; unknown on a first pass).
    "vendor_failing_pack": {"points": 79, "or": 3.0, "beta": 1.10, "model": "reply",
                            "group": "vendor_failing"},
    "vendor_failing_organic": {"points": 63, "or": 2.4, "beta": 0.88, "model": "reply",
                               "group": "vendor_failing"},

    # Case-study proof match. Top two bins `unavailable` at launch (AR holds no case studies in the
    # target verticals) — kept, not deleted, so they activate automatically (§Case-study).
    "case_same_vertical_comparable": {"points": 69, "or": 2.6, "beta": 0.96, "model": "reply",
                                      "group": "case_study", "status": "unavailable"},
    "case_same_vertical_any": {"points": 42, "or": 1.8, "beta": 0.59, "model": "reply",
                               "group": "case_study", "status": "unavailable"},
    "case_adjacent_comparable": {"points": 24, "or": 1.4, "beta": 0.34, "model": "reply",
                                 "group": "case_study"},
    "case_none": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply", "group": "case_study", **_R},

    # Geogrid pain (primary discriminator).
    "geogrid_lt20_steep": {"points": 57, "or": 2.2, "beta": 0.79, "model": "reply",
                           "group": "geogrid_pain"},
    "geogrid_20_50": {"points": 24, "or": 1.4, "beta": 0.34, "model": "reply", "group": "geogrid_pain"},
    "geogrid_50_80": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply",
                      "group": "geogrid_pain", **_R},
    "geogrid_gt80": {"points": -50, "or": 0.5, "beta": -0.69, "model": "reply", "group": "geogrid_pain"},

    # GBP quality gate.
    "gbp_strong": {"points": 34, "or": 1.6, "beta": 0.47, "model": "reply", "group": "gbp_gate"},
    "gbp_adequate": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply", "group": "gbp_gate", **_R},
    "gbp_weak": {"points": -26, "or": 0.7, "beta": -0.36, "model": "reply", "group": "gbp_gate"},

    # Organic / AI pain — INDEPENDENT additive one-directional flags (they co-occur; F1 fires both
    # organic_absent and ai_absent_0of3). Absence never subtracts (unknown = absent).
    "organic_absent": {"points": 10, "or": 1.15, "beta": 0.14, "model": "reply",
                       "group": None, "one_directional": True},
    "ai_absent_0of3": {"points": 13, "or": 1.20, "beta": 0.18, "model": "reply",
                       "group": None, "one_directional": True},
    "ai_cites_competitors": {"points": 16, "or": 1.25, "beta": 0.22, "model": "reply",
                             "group": None, "one_directional": True},

    # Buying intent — INDEPENDENT additive one-directional flags (F1 fires ads_gap + aw_tag +
    # meta_pixel). Absence never subtracts (§Buying intent).
    "lsa_present_absent_pack": {"points": 50, "or": 2.0, "beta": 0.69, "model": "reply",
                                "group": None, "one_directional": True},
    "ads_gap": {"points": 46, "or": 1.9, "beta": 0.64, "model": "reply",
                "group": None, "one_directional": True},
    "aw_tag": {"points": 19, "or": 1.3, "beta": 0.26, "model": "reply",
               "group": None, "one_directional": True},
    "vendor_tag": {"points": 16, "or": 1.25, "beta": 0.22, "model": "reply",
                   "group": None, "one_directional": True},
    "meta_pixel": {"points": 10, "or": 1.15, "beta": 0.14, "model": "reply",
                   "group": None, "one_directional": True},

    # Decision structure.
    "owner_operated": {"points": 29, "or": 1.5, "beta": 0.41, "model": "reply",
                       "group": "decision_structure"},
    "independent": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply",
                    "group": "decision_structure", **_R},
    "likely_represented": {"points": -21, "or": 0.75, "beta": -0.29, "model": "reply",
                           "group": "decision_structure"},
    "franchise": {"points": -87, "or": 0.3, "beta": -1.20, "model": "reply",
                  "group": "decision_structure"},

    # Trajectory — two co-occurring exclusive sub-dimensions (F3 fires velocity_growing +
    # reviews_top_quartile).
    "velocity_declining": {"points": 19, "or": 1.3, "beta": 0.26, "model": "reply", "group": "velocity"},
    "velocity_growing": {"points": 13, "or": 1.2, "beta": 0.18, "model": "reply", "group": "velocity"},
    "velocity_flat": {"points": 0, "or": 1.0, "beta": 0.0, "model": "reply", "group": "velocity", **_R},
    "reviews_top_quartile": {"points": -12, "or": 0.85, "beta": -0.16, "model": "reply",
                             "group": "review_count_quartile"},
    "reviews_bottom_quartile": {"points": 7, "or": 1.1, "beta": 0.10, "model": "reply",
                                "group": "review_count_quartile"},

    # --- Model B (close | reply) — §3. Weights shift toward budget + decision authority. --------
    "close_owner_dm": {"points": 79, "or": 3.0, "beta": 1.10, "model": "close",
                       "group": "close_decision_authority"},
    "close_franchise_corporate": {"points": -116, "or": 0.2, "beta": -1.61, "model": "close",
                                  "group": "close_decision_authority"},
    "close_spend_gt2k": {"points": 66, "or": 2.5, "beta": 0.92, "model": "close",
                         "group": "close_ad_spend_band"},
    "close_spend_500_2k": {"points": 34, "or": 1.6, "beta": 0.47, "model": "close",
                           "group": "close_ad_spend_band"},
    "close_lsa_active": {"points": 57, "or": 2.2, "beta": 0.79, "model": "close",
                         "group": None, "one_directional": True},
    "close_vendor_tags": {"points": 42, "or": 1.8, "beta": 0.59, "model": "close",
                          "group": "close_displaceable_budget"},
    "close_vendor_failing": {"points": 90, "or": 3.5, "beta": 1.25, "model": "close",
                             "group": "close_displaceable_budget"},
    "close_likely_represented": {"points": -26, "or": 0.7, "beta": -0.36, "model": "close",
                                 "group": None, "one_directional": True},
    "close_reviews_top_quartile": {"points": 29, "or": 1.5, "beta": 0.41, "model": "close",
                                   "group": "close_review_capacity"},
    "close_reviews_bottom_quartile": {"points": -37, "or": 0.6, "beta": -0.51, "model": "close",
                                      "group": "close_review_capacity"},
    "close_multi_location": {"points": 38, "or": 1.7, "beta": 0.53, "model": "close",
                             "group": None, "one_directional": True},
    "close_years_gt5": {"points": 24, "or": 1.4, "beta": 0.34, "model": "close",
                        "group": None, "one_directional": True},
    "close_pain_geogrid_lt20": {"points": 13, "or": 1.2, "beta": 0.18, "model": "close",
                                "group": None, "one_directional": True},
}


@dataclass(frozen=True)
class ScorecardParams:
    """Everything the engine needs, assembled from Settings + the registry + any JSON override.

    Immutable: a run stamps `model_version` and the effective params, and re-scoring is a new run.
    """

    pdo: float
    target: float
    lambda_shrink: float
    factor: float
    offset_email: float
    offset_phone: float
    offset_close: float
    base_rate_reply_email: float
    base_rate_reply_phone: float
    base_rate_close: float
    display_prob_clamp_pct: float
    r_base: float
    t_base: float
    model_version: str
    # bin name -> resolved integer points (registry default, then JSON override applied).
    points: dict[str, float] = field(default_factory=dict)
    # bin name -> full metadata dict (for score_factors: or, beta, model, group, status, ...).
    meta: dict[str, dict] = field(default_factory=dict)

    def offset_for(self, model: str, channel: str) -> float | None:
        """The probability offset (scoring-spec §1). None for `value` (a composition, not a scorecard).

        `close` is channel-independent (§3, "both") — same offset whatever channel it is stamped with.
        """
        if model == "reply":
            return self.offset_email if channel == "email" else self.offset_phone
        if model == "close":
            return self.offset_close
        return None

    def points_for(self, bin_name: str) -> float:
        try:
            return self.points[bin_name]
        except KeyError as exc:  # a typo in extraction must fail loudly, never score as 0
            raise KeyError(f"unknown scorecard bin {bin_name!r}") from exc

    def group_of(self, bin_name: str) -> str | None:
        return self.meta[bin_name].get("group")

    def bins_for_model(self, model: str) -> list[str]:
        return [name for name, m in self.meta.items() if m["model"] == model]


def _apply_overrides(base: dict[str, float], override_json: str) -> dict[str, float]:
    """Overlay a JSON `{bin: points}` object onto the registry defaults. Empty = defaults."""
    points = dict(base)
    text = (override_json or "").strip()
    if not text:
        return points
    try:
        override = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OUTREACH_SCORECARD_COEFFICIENTS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(override, dict):
        raise ValueError("OUTREACH_SCORECARD_COEFFICIENTS_JSON must be a JSON object {bin: points}")
    for bin_name, value in override.items():
        if bin_name not in base:
            raise ValueError(f"override names unknown scorecard bin {bin_name!r}")
        points[bin_name] = float(value)
    return points


def load_params(settings) -> ScorecardParams:
    """Assemble the effective scorecard parameters from a Settings instance.

    Pure w.r.t. the settings passed in; the JSON override is validated here so a bad override
    refuses at load rather than mis-scoring a whole market.
    """
    factor = factor_of(settings.score_pdo)
    base_points = {name: float(spec["points"]) for name, spec in COEFFICIENTS.items()}
    points = _apply_overrides(base_points, settings.scorecard_coefficients_json)
    return ScorecardParams(
        pdo=settings.score_pdo,
        target=settings.score_target,
        lambda_shrink=settings.score_lambda_shrink,
        factor=factor,
        offset_email=settings.score_offset_email,
        offset_phone=settings.score_offset_phone,
        offset_close=settings.score_offset_close,
        base_rate_reply_email=settings.score_base_rate_reply_email,
        base_rate_reply_phone=settings.score_base_rate_reply_phone,
        base_rate_close=settings.score_base_rate_close,
        display_prob_clamp_pct=settings.score_display_prob_clamp_pct,
        r_base=settings.score_r_base,
        t_base=settings.score_t_base,
        model_version=settings.score_model_version,
        points=points,
        meta=dict(COEFFICIENTS),
    )
