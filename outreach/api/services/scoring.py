"""The score RUN (scoring-spec.md §6 Stage 1). Reads stored signals, writes score_run +
prospect_score. Deterministic and fact-grounded — makes NO paid provider call, so it is not in
PAID_COMMANDS (the same posture as `rollup`/`collect`).

Pure core (`build_inputs`, `score_one`, `assign_deciles`, `to_records`) is unit-tested; the I/O
wrapper (`run_score`) reads the measured set from `v_prospect_placeholder_score` (which already bakes
in the I-076 / snapshot-marker gating — a prospect with no coverage row inside a measured submarket
is 0% coverage, and an unmeasured submarket yields no rows) and joins the prospect + tech signals.

STAGE 1 SCOPE (logged in DECISIONS): the live run scores the PHONE track at PASS 1 — phone-first,
pre-enrichment. Email reachability needs enrichment (Phase 5, pass 2), and the whole design is
phone-first, so producing email rows now would rank an unreachable channel. The engine and golden
fixtures prove the email path; the job lights it up when enrichment lands. `close` is
channel-independent but stamped with the channel it composes into a `value` (the PK requires it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from api.services import score_features as sf
from api.services import scorecard, scorecard_config as sc
from api.services.paging import fetch_all

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredProspect:
    prospect_id: str
    channel: str
    pass_number: int
    reply: scorecard.ScoreResult
    close: scorecard.ScoreResult
    value: scorecard.ValueResult
    primary_pitch: str
    evidence_age_days: int


def build_inputs(view_row: dict, prospect_row: dict, tech_row: dict | None,
                 review_dist: sf.ReviewDistribution | None,
                 organic_summary: dict | None = None) -> sf.FeatureInputs:
    """Assemble a prospect's FeatureInputs from its coverage view row + base pull + tech signal +
    (optionally) the organic SERP captured for its submarket.

    A missing tech_row means scan-tech has not run for this prospect -> tech_scanned False -> every
    tech flag is unknown==absent (never fired). `organic_summary` is the stored
    `serp_result.payload_summary` for the prospect's submarket (or None when no organic scan has run
    there) — its match against the prospect's website drives the organic-presence features (default
    None keeps the pre-organic behaviour, so a caller that doesn't pass it is unchanged). Pure.
    """
    tech = tech_row or {}
    tech_scanned = bool(tech_row) and (tech.get("fetch_status") == "ok")
    vendor_tags = tech.get("vendor_tags") or []
    gtm = tech.get("gtm_container_ids") or []
    # likely_represented mirrors tech_signals.TechSignals.likely_represented (2+ marketing-stack signals).
    agency_signals = len(vendor_tags) + (1 if gtm else 0)

    review_count = prospect_row.get("review_count")
    quartile = review_dist.quartile(review_count) if review_dist else None

    # Organic presence: matched from the submarket's captured SERP against the prospect's website.
    # Not scanned (no SERP for the submarket) => scanned False => every organic bin stays dormant
    # (unknown==absent, the same discipline as tech).
    org = sf.organic_signal(organic_summary, prospect_row.get("website"))

    return sf.FeatureInputs(
        coverage_pct=view_row.get("coverage_pct"),
        best_rank=view_row.get("best_rank"),
        centroid_dist_at_loss=view_row.get("centroid_dist_at_loss"),
        franchise_status=prospect_row.get("franchise_status"),
        phone_type=prospect_row.get("phone_type"),
        rating=prospect_row.get("rating"),
        review_count=review_count,
        review_quartile=quartile,
        # owner_operated / multi_location / years_in_business are not captured in Stage 1 -> None.
        tech_scanned=tech_scanned,
        meta_pixel=bool(tech.get("meta_pixel")),
        aw_tag=bool(tech.get("google_ads_conversion")),
        vendor_tag=bool(vendor_tags),
        google_guaranteed=bool(tech.get("google_guaranteed")),
        likely_represented=agency_signals >= 2,
        organic_scanned=org.scanned,
        organic_absent=org.absent,
        top10_organic=org.top10,
        # ai / delta sources are not run for this prospect -> unknown==absent.
    )


def score_one(inputs: sf.FeatureInputs, *, channel: str, pass_number: int,
              params: sc.ScorecardParams, thresholds, evidence_age_days: int,
              prospect_id: str,
              reply_calibration: tuple[float, float] | None = None) -> ScoredProspect:
    """Score one prospect on one channel: reply, close, and the composed value. Pure.

    `reply_calibration` (alpha, gamma) is the Stage-2 recalibration (scoring-spec §6). When present,
    it transforms the reply probability (and cascades to value) WITHOUT changing score/decile — the
    transform is monotone, so rank order is preserved. Absent = Stage-1 priors (no correction).
    """
    reply_sel = sf.reply_bins(inputs, channel=channel, pass_number=pass_number, thresholds=thresholds)
    close_sel = sf.close_bins(inputs, thresholds=thresholds)
    # Catch an extraction bug (two bins from one exclusive group) before it double-counts.
    scorecard.validate_selection(reply_sel, model="reply", params=params)
    scorecard.validate_selection(close_sel, model="close", params=params)

    reply = scorecard.score_model(reply_sel, channel=channel, model="reply", params=params)
    close = scorecard.score_model(close_sel, channel=channel, model="close", params=params)
    if reply_calibration is not None and reply.predicted_prob is not None:
        alpha, gamma = reply_calibration
        reply = replace(
            reply, predicted_prob=scorecard.apply_calibration(reply.predicted_prob, alpha, gamma)
        )
    value = scorecard.compose_value(
        reply.predicted_prob, close.predicted_prob, channel=channel, params=params
    )
    pitch = sf.primary_pitch(inputs, reply_sel)
    return ScoredProspect(
        prospect_id=prospect_id, channel=channel, pass_number=pass_number,
        reply=reply, close=close, value=value, primary_pitch=pitch,
        evidence_age_days=evidence_age_days,
    )


def assign_deciles(scores: list[float]) -> list[int]:
    """Decile 1..10 (10 = highest) by ascending rank, ~equal buckets. Pure, ties-stable.

    Ranking is the model's stated priority (scoring-spec §Evaluation), and precision matters most at
    the top of the distribution (§4), so deciles are the honest granularity to expose while scores
    are ordinal-only. A single-element or empty input degrades sensibly.
    """
    n = len(scores)
    if n == 0:
        return []
    if n == 1:
        return [10]  # a lone prospect is the top of its own distribution, not the bottom
    order = sorted(range(n), key=lambda i: scores[i])
    deciles = [0] * n
    for rank, idx in enumerate(order):
        # rank 0..n-1 -> decile 1..10; guarantees the max element lands in decile 10 for every n>=2.
        deciles[idx] = 1 + (9 * rank) // (n - 1)
    return deciles


def to_records(scored: list[ScoredProspect], *, score_run_id: str) -> list[dict]:
    """Build prospect_score rows for every (prospect, model), with deciles assigned per (model,
    channel) across the run population. Pure — takes the score_run_id the caller minted."""
    records: list[dict] = []
    # Deciles are computed per (model, channel) group.
    by_group: dict[tuple[str, str], list[int]] = {}
    for i, s in enumerate(scored):
        by_group.setdefault(("reply", s.channel), []).append(i)
        by_group.setdefault(("close", s.channel), []).append(i)
        by_group.setdefault(("value", s.channel), []).append(i)

    decile_of: dict[tuple[int, str], int] = {}
    for (model, channel), idxs in by_group.items():
        if model == "reply":
            vals = [scored[i].reply.score for i in idxs]
        elif model == "close":
            vals = [scored[i].close.score for i in idxs]
        else:
            vals = [scored[i].value.score for i in idxs]
        for pos, dec in zip(idxs, assign_deciles(vals)):
            decile_of[(pos, model)] = dec

    for i, s in enumerate(scored):
        common = {
            "score_run_id": score_run_id,
            "prospect_id": s.prospect_id,
            "pass": s.pass_number,
            "channel": s.channel,
            "primary_pitch": s.primary_pitch,
            "evidence_age_days": s.evidence_age_days,
        }
        records.append({**common, "model": "reply",
                        "raw_points": s.reply.raw_points, "score": s.reply.score,
                        "predicted_prob": s.reply.predicted_prob,
                        "decile": decile_of[(i, "reply")],
                        "score_factors": s.reply.score_factors})
        records.append({**common, "model": "close",
                        "raw_points": s.close.raw_points, "score": s.close.score,
                        "predicted_prob": s.close.predicted_prob,
                        "decile": decile_of[(i, "close")],
                        "score_factors": s.close.score_factors})
        records.append({**common, "model": "value",
                        "raw_points": s.value.raw_points, "score": s.value.score,
                        "predicted_prob": s.value.predicted_prob,
                        "decile": decile_of[(i, "value")],
                        "score_factors": s.value.score_factors})
    return records


@dataclass
class ScoreReport:
    market_id: str
    score_run_id: str | None
    cycle_number: int
    scored: int
    rows_written: int
    channels: tuple[str, ...]
    pass_number: int
    review_distribution: tuple[float, float] | None
    problems: list[str]


def _read_measured(client, market_id: str) -> list[dict]:
    return fetch_all(
        lambda: client.table("v_prospect_placeholder_score")
        .select("prospect_id, submarket_id, coverage_pct, best_rank, "
                "centroid_dist_at_loss, excluded, measured_at")
        .eq("market_id", market_id)
    )


def _read_by_ids(client, table: str, id_column: str, columns: str, ids: list[str]) -> dict[str, dict]:
    """Read `table` for a set of prospect ids, chunked to keep the URL under PostgREST's limit."""
    out: dict[str, dict] = {}
    CHUNK = 200
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        rows = (
            client.table(table).select(columns).in_(id_column, chunk).execute().data or []
        )
        for row in rows:
            out[row[id_column]] = row
    return out


def _read_organic_by_submarket(client, submarket_ids: list[str]) -> dict[str, dict]:
    """{submarket_id: latest serp_result.payload_summary} for the given submarkets.

    The organic SERP is captured per SNAPSHOT (submarket x keyword — `scan-organic`); a prospect's
    organic rank is the match against its submarket's most recent captured SERP. Reads scan_snapshot
    for the submarkets, then serp_result for those snapshots, and keeps — per submarket — the summary
    from the latest snapshot that carries one. Chunked under the PostgREST cap. A submarket with no
    organic scan simply doesn't appear (=> None => unknown==absent, no organic bin fires). Best-effort:
    an unreadable serp_result table degrades to {} (organic dormant, never blocks the score run)."""
    if not submarket_ids:
        return {}
    CHUNK = 200
    snap_meta: dict[str, tuple[str, str]] = {}  # snapshot_id -> (submarket_id, scanned_at)
    try:
        for start in range(0, len(submarket_ids), CHUNK):
            chunk = submarket_ids[start:start + CHUNK]
            for row in (client.table("scan_snapshot")
                        .select("id, submarket_id, scanned_at")
                        .in_("submarket_id", chunk).execute().data or []):
                snap_meta[row["id"]] = (row["submarket_id"], row.get("scanned_at") or "")
        if not snap_meta:
            return {}
        snap_ids = list(snap_meta.keys())
        best: dict[str, tuple[str, dict]] = {}  # submarket_id -> (scanned_at, summary) of the latest
        for start in range(0, len(snap_ids), CHUNK):
            chunk = snap_ids[start:start + CHUNK]
            for row in (client.table("serp_result")
                        .select("snapshot_id, payload_summary")
                        .in_("snapshot_id", chunk).execute().data or []):
                summary = row.get("payload_summary")
                meta = snap_meta.get(row.get("snapshot_id"))
                if not summary or not meta:
                    continue
                submarket_id, scanned_at = meta
                cur = best.get(submarket_id)
                if cur is None or scanned_at > cur[0]:
                    best[submarket_id] = (scanned_at, summary)
        return {sub: summ for sub, (_ts, summ) in best.items()}
    except Exception as exc:  # noqa: BLE001 — organic is additive; never fail a score run over it
        logger.warning("organic SERP read for scoring failed", extra={"error": str(exc)[:200]})
        return {}


def run_score(client, settings, *, market_id: str, cycle_number: int,
              channels: tuple[str, ...] = ("phone",), pass_number: int = 1,
              calibration: dict[str, tuple[float, float]] | None = None,
              now: datetime | None = None) -> ScoreReport:
    """Score a market's measured, non-excluded prospects and write one immutable score_run.

    Non-excluded only: the ranked queue is who to CALL, and an excluded prospect failed a filter and
    is not callable (eligibility, distinct from the conflict flag — DECISIONS). A re-run inserts a
    NEW score_run; history is never mutated.

    `calibration` (Stage 2, {channel: (alpha, gamma)}) recalibrates the reply probability and stamps
    the run's calibration_alpha/gamma, which lifts the display clamp (acceptance §5). None = Stage 1
    priors. score_run carries a single alpha/gamma pair, so a calibrated run is single-channel (the
    phone-first reality — a per-channel calibration store is a later migration when email is live).
    """
    calibration = calibration or {}
    now = now or datetime.now(timezone.utc)
    params = sc.load_params(settings)
    problems: list[str] = []

    measured = _read_measured(client, market_id)
    scorable = [r for r in measured if not r.get("excluded")]
    if not scorable:
        logger.info("no measured, non-excluded prospects to score", extra={"market_id": market_id})
        return ScoreReport(market_id, None, cycle_number, 0, 0, channels, pass_number, None, problems)

    ids = [r["prospect_id"] for r in scorable]
    prospects = _read_by_ids(
        client, "prospect", "id",
        "id, name, franchise_status, phone_type, rating, review_count, website", ids,
    )
    tech = _read_by_ids(
        client, "prospect_tech_signal", "prospect_id",
        "prospect_id, fetch_status, meta_pixel, google_ads_conversion, vendor_tags, "
        "gtm_container_ids, google_guaranteed", ids,
    )
    # The organic SERP captured per submarket (scan-organic). Keyed by submarket so each prospect
    # reads the SERP for ITS submarket; a submarket with no organic scan yet contributes None
    # (unknown==absent). Derived per prospect from its website domain vs the SERP inside build_inputs.
    organic_by_submarket = _read_organic_by_submarket(
        client, sorted({r["submarket_id"] for r in scorable if r.get("submarket_id")})
    )

    review_dist = sf.review_distribution(
        [p.get("review_count") for p in prospects.values() if p.get("review_count") is not None]
    )

    scored: list[ScoredProspect] = []
    for row in scorable:
        pid = row["prospect_id"]
        prospect_row = prospects.get(pid)
        if prospect_row is None:
            problems.append(f"prospect {pid} in coverage view but not in prospect table")
            continue
        inputs = build_inputs(
            row, prospect_row, tech.get(pid), review_dist,
            organic_summary=organic_by_submarket.get(row.get("submarket_id")),
        )
        measured_at = _parse_ts(row.get("measured_at"))
        age_days = max(0, (now - measured_at).days) if measured_at else 0
        for channel in channels:
            scored.append(score_one(
                inputs, channel=channel, pass_number=pass_number, params=params,
                thresholds=settings, evidence_age_days=age_days, prospect_id=pid,
                reply_calibration=calibration.get(channel),
            ))

    # A calibrated run stamps its (single) channel's alpha/gamma; a Stage-1 run leaves them null.
    run_alpha, run_gamma = (None, None)
    if len(calibration) == 1:
        (run_alpha, run_gamma), = calibration.values()

    # Mint the run, then write every score row against it.
    run = (
        client.table("score_run").insert({
            "market_id": market_id,
            "cycle_number": cycle_number,
            "model_version": params.model_version,
            "lambda_shrink": params.lambda_shrink,
            "calibration_alpha": run_alpha,
            "calibration_gamma": run_gamma,
        }).execute().data
    )
    score_run_id = run[0]["id"]

    records = to_records(scored, score_run_id=score_run_id)
    written = 0
    CHUNK = 500
    for start in range(0, len(records), CHUNK):
        client.table("prospect_score").insert(records[start:start + CHUNK]).execute()
        written += len(records[start:start + CHUNK])

    return ScoreReport(
        market_id=market_id, score_run_id=score_run_id, cycle_number=cycle_number,
        scored=len(scored), rows_written=written, channels=channels, pass_number=pass_number,
        review_distribution=(review_dist.p25, review_dist.p75) if review_dist else None,
        problems=problems,
    )


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
