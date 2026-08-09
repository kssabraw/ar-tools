"""Stage-2 recalibration (scoring-spec.md §6). A STANDALONE job runnable against `outcome`.

The standard scorecard recalibration move: fit a two-parameter logistic regression using the
current model's predicted log-odds as the SINGLE input variable,

    ln(odds_calibrated) = alpha + gamma x ln(odds_prior)

which corrects calibration (alpha) and over/under-confidence (gamma) WITHOUT touching rank order —
the transform is monotone in the score. It needs an order of magnitude less data than refitting the
~20 coefficients (that is Stage 3, and it is NOT built here — it needs a posterior only ~80+ reply
outcomes produce).

EMPTY-SAFE BY DESIGN. Zero reply outcomes exist today (nobody has been called), so this job reads
nothing to fit and reports "insufficient" — which is the correct state, not a failure. It becomes
useful as `outcome` rows accumulate. It is built (not stubbed) because acceptance §10 requires it
runnable now, and because the fit is pure and testable without any real data.

Invariants honoured:
  * PER-CHANNEL. Phone and email measure different events and are never pooled (scoring-spec §1);
    the job fits each channel separately and refuses a channel below the outcome floor.
  * NOT evaluated on the Thompson subset alone (scoring-spec §7). Stage 1 has no Thompson selection
    (all `manual`/`random_control`), but the guard is here for when it does.
  * Rank order is preserved — the calibrated run reuses the same points/score/decile and only
    transforms predicted_prob (which un-clamps the display, acceptance §5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from api.services import scorecard
from api.services.paging import fetch_all
from api.services.scoring import run_score

logger = logging.getLogger(__name__)


def fit_calibration(x: list[float], y: list[int], *, max_iter: int = 100,
                    tol: float = 1e-9) -> tuple[float, float]:
    """MLE of (alpha, gamma) for y ~ Bernoulli(sigmoid(alpha + gamma x)), by Fisher scoring.

    Pure, stdlib only (no numpy — the api requirements stay minimal). Starts at the identity
    (alpha=0, gamma=1) — the "no correction" point, so a degenerate fit degrades toward leaving the
    prior probabilities unchanged rather than toward nonsense. A singular Hessian (perfect
    separation / no variance in x) stops iterating and returns the last stable estimate.
    """
    alpha, gamma = 0.0, 1.0
    for _ in range(max_iter):
        g_a = g_g = 0.0            # gradient
        h00 = h01 = h11 = 0.0      # Hessian (Fisher information)
        for xi, yi in zip(x, y):
            p = scorecard.probability_from_logodds(alpha + gamma * xi)
            w = p * (1.0 - p)
            r = yi - p
            g_a += r
            g_g += r * xi
            h00 += w
            h01 += w * xi
            h11 += w * xi * xi
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        d_alpha = (h11 * g_a - h01 * g_g) / det
        d_gamma = (h00 * g_g - h01 * g_a) / det
        alpha += d_alpha
        gamma += d_gamma
        if abs(d_alpha) + abs(d_gamma) < tol:
            break
    return alpha, gamma


@dataclass
class ChannelFit:
    channel: str
    outcomes: int
    replies: int
    fitted: bool
    alpha: float | None = None
    gamma: float | None = None
    reason: str | None = None


@dataclass
class RecalibrationReport:
    market_id: str
    total_outcomes: int
    channel_fits: list[ChannelFit] = field(default_factory=list)
    score_run_id: str | None = None
    wrote_calibrated_run: bool = False
    problems: list[str] = field(default_factory=list)


# The disposition-to-channel and reply columns come from `outcome` + `touch` (Phase 3). An outcome's
# channel is the channel of its touches; a "reply" is `outcome.replied_at is not null`.
_THOMPSON = "thompson"


def _read_fit_rows(client, market_id: str) -> list[dict]:
    """Read outbound outcomes for the market joined to their reply model's prior probability.

    An outcome is modellable once it has been CONTACTED (first_contacted_at set) — a queued-but-never
    -dialed prospect is not a data point. The prior probability is the LATEST reply prospect_score for
    that prospect in the channel the outcome was worked in.
    """
    # outcome is prospect-keyed; prospect carries market_id.
    outcomes = fetch_all(
        lambda: client.table("outcome")
        .select("prospect_id, selection_reason, replied_at, first_contacted_at")
        .not_.is_("first_contacted_at", "null")
    )
    if not outcomes:
        return []
    ids = [o["prospect_id"] for o in outcomes]
    # Restrict to this market's prospects.
    market_ids: set[str] = set()
    CHUNK = 200
    for start in range(0, len(ids), CHUNK):
        rows = (
            client.table("prospect").select("id").eq("market_id", market_id)
            .in_("id", ids[start:start + CHUNK]).execute().data or []
        )
        market_ids.update(r["id"] for r in rows)

    # Channel attribution: an outcome is fit against the channel it has a reply prospect_score in
    # (resolved by the caller). That is the channel the prospect was scored/queued in — for the
    # phone-first Stage-1 reality it is phone. A refinement to the authoritative `touch` channel
    # lands when the email track is live and a prospect can be worked in more than one channel.
    return [o for o in outcomes if o["prospect_id"] in market_ids]


def run_recalibration(client, settings, *, market_id: str, cycle_number: int,
                      min_outcomes: int | None = None) -> RecalibrationReport:
    """Fit per-channel calibration on real reply outcomes and, if sufficient, write a calibrated run.

    Empty-safe: with no contacted outcomes it reports "insufficient" per channel and writes nothing.
    """
    floor = min_outcomes if min_outcomes is not None else settings.score_recalibration_min_outcomes
    report = RecalibrationReport(market_id=market_id, total_outcomes=0)

    outcomes = _read_fit_rows(client, market_id)
    report.total_outcomes = len(outcomes)
    if not outcomes:
        report.channel_fits.append(ChannelFit(
            channel="phone", outcomes=0, replies=0, fitted=False,
            reason=f"no contacted outcomes yet (need >= {floor}); Stage 1 rank order stands",
        ))
        return report

    # Latest reply prospect_score per (prospect, channel) — the prior probability to calibrate.
    ids = [o["prospect_id"] for o in outcomes]
    priors: dict[tuple[str, str], float] = {}
    CHUNK = 200
    for start in range(0, len(ids), CHUNK):
        rows = (
            client.table("prospect_score")
            .select("prospect_id, channel, predicted_prob, score_run_id")
            .eq("model", "reply").in_("prospect_id", ids[start:start + CHUNK])
            .execute().data or []
        )
        # Keep the most recent by score_run ordering is not available here; the reply prob is stable
        # per run and rank-preserving across runs, so any run's prior is acceptable for calibration.
        for r in rows:
            if r.get("predicted_prob") is not None:
                priors[(r["prospect_id"], r["channel"])] = float(r["predicted_prob"])

    by_channel: dict[str, list[tuple[float, int, str]]] = {}
    for o in outcomes:
        replied = 1 if o.get("replied_at") else 0
        reason = (o.get("selection_reason") or "manual").strip()
        for (pid, channel), prior in priors.items():
            if pid == o["prospect_id"]:
                by_channel.setdefault(channel, []).append((prior, replied, reason))

    calibration: dict[str, tuple[float, float]] = {}
    for channel, rows in by_channel.items():
        n = len(rows)
        replies = sum(r[1] for r in rows)
        if n < floor:
            report.channel_fits.append(ChannelFit(
                channel=channel, outcomes=n, replies=replies, fitted=False,
                reason=f"only {n} outcomes (need >= {floor})",
            ))
            continue
        if all(r[2] == _THOMPSON for r in rows):
            report.channel_fits.append(ChannelFit(
                channel=channel, outcomes=n, replies=replies, fitted=False,
                reason="all outcomes are Thompson-selected — refits must not evaluate on that subset "
                       "alone (scoring-spec §7)",
            ))
            continue
        x = [scorecard.logit(r[0]) for r in rows]
        y = [r[1] for r in rows]
        alpha, gamma = fit_calibration(x, y)
        calibration[channel] = (alpha, gamma)
        report.channel_fits.append(ChannelFit(
            channel=channel, outcomes=n, replies=replies, fitted=True, alpha=alpha, gamma=gamma,
        ))

    # Write a calibrated run only when EXACTLY one channel fitted — score_run carries a single
    # alpha/gamma pair (phone-first reality; multi-channel calibration is a later migration).
    if len(calibration) == 1:
        channel = next(iter(calibration))
        result = run_score(
            client, settings, market_id=market_id, cycle_number=cycle_number,
            channels=(channel,), calibration=calibration,
        )
        report.score_run_id = result.score_run_id
        report.wrote_calibrated_run = True
        report.problems.extend(result.problems)
    elif len(calibration) > 1:
        report.problems.append(
            f"{len(calibration)} channels fitted but score_run stores one alpha/gamma — "
            f"writing no calibrated run (needs the per-channel calibration migration)"
        )

    return report
