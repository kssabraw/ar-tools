"""LeadOff calibration surface — Phase 0 instrumentation ONLY.

Spec: docs/modules/leadoff-calibration-plan-v1_0.md (owner-approved
2026-07-12, §7 rulings). Captures the prediction vector losslessly at the
create-client seam and appends read-only outcome checks as reality accrues.
NOTHING here feeds back into scoring — Phase 1 (weight tuning) is gated on
per-metric N≥15 with ≥6-month tenure and does not exist yet.

Owner rulings encoded here:
  * keyword tracking stays MANUAL — rankability outcomes exist only where the
    team tracked a matching keyword; missing sources become explicit coverage
    reasons, never silent skips.
  * maps "ranked" bar = ≥50% top-3 pin share (MAPS_RANKED_SHARE).
  * horizons 3/6/12 months (reporting buckets; checks append monthly).
  * manual lead entry surfaces on the Campaign Goals page (API here).

All sweep reads are DB-only — $0, no paid calls.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

MAPS_RANKED_SHARE = 50.0          # §7 ruling: ≥50% top-3 pin share
ORGANIC_RANKED_POSITION = 10      # organic "ranked" = position ≤ 10
CHECK_SPACING_DAYS = 28           # one outcome check per prediction per ~month
HORIZONS_MONTHS = (3, 6, 12)
_DAYS_PER_MONTH = 30.44

# §5.2: the scoring constants in force when the prediction was made — stamped
# on every row so post-tuning predictions are never scored against pre-tuning
# assumptions. Board rows are precomputed by the scanner; these mirror
# report.py / check_city.py (docs/reference/leadoff-scanner/).
MODEL_VERSION = {
    "rankability": "0.75/(1+avg5/50)+0.25/(1+holders/5)",
    "xdemand": "0.75*win(obs,4x)+0.25*expected",
    "vetoes": {"min_leads_mo": 5, "min_rankab": 0.15},
    "roi_floor": 10,
    "source": "board",
}


# ── Pure helpers (unit-tested in tests/test_leadoff_calibration.py) ───────────

def months_elapsed(created_at: datetime, now: datetime) -> float:
    return round(max((now - created_at).days, 0) / _DAYS_PER_MONTH, 1)


def horizon_bucket(months: float) -> Optional[int]:
    """The nearest reporting horizon a check speaks to (None below ~2.5mo)."""
    for h in HORIZONS_MONTHS:
        if months <= h * 1.34:
            return h if months >= h * 0.67 else None
    return HORIZONS_MONTHS[-1]


def frozen_bar(competitors: list[dict[str, Any]]) -> Optional[int]:
    """The #3 incumbent's review count at selection — rev_win's original bar.
    Mirrors the scanner: 3rd-highest top-5 review count."""
    revs = sorted((int(c.get("review_count") or 0) for c in competitors or []),
                  reverse=True)
    if not revs:
        return None
    return revs[min(2, len(revs) - 1)]


def live_bar(review_counts: list[int]) -> Optional[int]:
    """The current #3 among the tracked competitors (bar drift vs frozen)."""
    revs = sorted((int(v) for v in review_counts if v is not None), reverse=True)
    if not revs:
        return None
    return revs[min(2, len(revs) - 1)]


def match_keyword(tracked: list[dict[str, Any]], category: str,
                  city_name: str) -> Optional[dict[str, Any]]:
    """Best tracked keyword for the predicted market: prefers one containing
    both category and city, falls back to category-only. Manual tracking is
    an owner ruling — no match is a coverage reason, not an error."""
    cat = (category or "").strip().casefold()
    city = (city_name or "").strip().casefold()
    if not cat:
        return None
    both, cat_only = None, None
    for k in tracked or []:
        kw = (k.get("keyword") or "").casefold()
        if cat in kw:
            if city and city in kw and both is None:
                both = k
            elif cat_only is None:
                cat_only = k
    return both or cat_only


def maps_share(results: list[dict[str, Any]], category: str) -> Optional[float]:
    """Top-3 pin share (0–100) from the latest scan's results whose keyword
    matches the category. None when no result matches."""
    cat = (category or "").strip().casefold()
    total = top3 = 0
    for r in results or []:
        if cat and cat in (r.get("keyword") or "").casefold():
            total += int(r.get("total_pins") or 0)
            top3 += int(r.get("top3_pins") or 0)
    return round(100.0 * top3 / total, 1) if total else None


def build_outcome(prediction: dict[str, Any], sources: dict[str, Any],
                  now: datetime) -> dict[str, Any]:
    """Assemble one outcome check from gathered sources. Pure. Unmeasurable
    metrics record None + a coverage reason — the report is honest about what
    it cannot yet see (plan §3/§4)."""
    predicted = prediction.get("predicted") or {}
    coverage: dict[str, str] = {}
    outcome: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    # rev_win → GBP review trajectory vs frozen AND live #3 bar (§3.1)
    client_reviews = sources.get("client_reviews")
    fbar = frozen_bar(prediction.get("competitors") or [])
    lbar = live_bar(sources.get("competitor_review_counts") or [])
    outcome["client_reviews"] = client_reviews
    outcome["frozen_bar"] = fbar
    outcome["live_bar"] = lbar
    if client_reviews is None:
        coverage["rev_win"] = "no client GBP review count yet"
    elif fbar is None:
        coverage["rev_win"] = "no frozen competitor bar (empty top-5 at capture)"
    else:
        outcome["bar_cleared"] = client_reviews > fbar
        if lbar is not None:
            # signed drift: how far the real bar moved from what rev_win assumed
            errors["bar_drift"] = lbar - int(predicted.get("rev_win") or fbar)
        else:
            coverage["live_bar"] = "no competitor GBP profiles captured yet"

    # rankability → maps pack share + organic position (§3.2; manual tracking)
    share = sources.get("maps_top3_share")
    outcome["maps_top3_share"] = share
    if share is None:
        coverage["rankab_maps"] = sources.get("maps_reason") or "no maps scan yet"
    else:
        outcome["ranked_maps"] = share >= MAPS_RANKED_SHARE
    pos = sources.get("organic_position")
    outcome["organic_position"] = pos
    if pos is None:
        coverage["rankab_organic"] = sources.get("organic_reason") or "no tracked keyword"
    else:
        outcome["ranked_organic"] = pos <= ORGANIC_RANKED_POSITION
    ranked_any = outcome.get("ranked_maps") or outcome.get("ranked_organic")
    if "ranked_maps" in outcome or "ranked_organic" in outcome:
        # Brier-style residual: (did we rank) − (predicted win-likelihood).
        # Meaningful only in aggregate — stored per row, judged at N.
        rankab = predicted.get("rankab")
        if rankab is not None:
            errors["rankab_residual"] = round((1.0 if ranked_any else 0.0)
                                              - float(rankab), 2)

    # leads (§3.3 — the hard gap; manual entries arrive via their own rows)
    coverage["exp_leads"] = "no lead feed — manual entry only (plan §3.3)"

    return {
        "outcome": outcome,
        "errors": errors,
        "coverage": coverage,
        "months_elapsed": months_elapsed(
            datetime.fromisoformat(str(prediction["created_at"]).replace("Z", "+00:00")),
            now),
    }


def summarize(predictions: list[dict[str, Any]],
              checks_by_prediction: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The read-only calibration report (plan §4.2): per-metric coverage +
    error stats where N permits + per-engagement latest snapshot. Pure."""
    per_metric = {"rev_win": 0, "rankab": 0, "leads": 0}
    engagements = []
    bar_drifts: list[float] = []
    rankab_residuals: list[float] = []
    for p in predictions:
        checks = sorted(checks_by_prediction.get(p["id"]) or [],
                        key=lambda c: c.get("checked_at") or "")
        latest = checks[-1] if checks else None
        out = (latest or {}).get("outcome") or {}
        errs = (latest or {}).get("errors") or {}
        if out.get("bar_cleared") is not None:
            per_metric["rev_win"] += 1
        if "ranked_maps" in out or "ranked_organic" in out:
            per_metric["rankab"] += 1
        if any(c.get("actual_leads_mo") is not None for c in checks):
            per_metric["leads"] += 1
        if errs.get("bar_drift") is not None:
            bar_drifts.append(float(errs["bar_drift"]))
        if errs.get("rankab_residual") is not None:
            rankab_residuals.append(float(errs["rankab_residual"]))
        engagements.append({
            "prediction_id": p["id"], "client_id": p.get("client_id"),
            "market": f"{p.get('category')} @ {p.get('city_name')}, {p.get('state_code')}",
            "as_of": p.get("as_of"), "created_at": p.get("created_at"),
            "predicted": p.get("predicted"),
            "months_elapsed": (latest or {}).get("months_elapsed"),
            "latest_outcome": out or None,
            "latest_errors": errs or None,
            "coverage_gaps": (latest or {}).get("coverage"),
            "checks": len(checks),
        })

    def _stats(vals: list[float]) -> Optional[dict[str, float]]:
        if len(vals) < 3:  # below this, numbers mislead more than inform
            return None
        s = sorted(vals)
        return {"n": len(vals), "mean": round(sum(vals) / len(vals), 2),
                "median": s[len(s) // 2]}

    return {
        "predictions": len(predictions),
        "coverage": per_metric,
        "bar_drift_stats": _stats(bar_drifts),
        "rankab_residual_stats": _stats(rankab_residuals),
        "engagements": engagements,
        "note": ("Phase 0 — read-only instrumentation. No scoring weight is "
                 "affected by anything here; tuning is gated on per-metric "
                 "N≥15 with ≥6-month tenure (plan §5)."),
    }


# ── Capture (at the create-client seam) ───────────────────────────────────────

def capture_prediction(client_id: str, brief: dict[str, Any], capture: float,
                       lead_tier: str, user_id: Optional[str],
                       proximity: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Freeze the full prediction vector at engagement creation. Best-effort —
    never fails the client (same policy as competitor/goal seeding).

    Captures the enriched grade + its `score_factors` and the proximity read so
    calibration can later test whether the enrichment signals (proximity,
    footprint, permits, seasonal) actually predicted the outcome — the loop
    that eventually tunes the enrichment weights."""
    predicted = {k: brief.get(k) for k in (
        "rev_win", "rankab", "xdem", "est_leads_mo", "exp_leads_mo",
        "value_mo", "exp_val", "grade", "build", "roi", "rating", "namekw",
        "exact_open", "luck", "conf", "v3", "population",
        # enrichment layer (score-enrichment v1) — the signals under test
        "base_grade", "base_exp_val", "base_rankab", "enriched", "score_factors")}
    lead_value = None
    if brief.get("value_mo") and brief.get("est_leads_mo"):
        try:
            lead_value = round(float(brief["value_mo"]) / float(brief["est_leads_mo"]), 2)
        except (ZeroDivisionError, TypeError, ValueError):
            lead_value = None
    try:
        row = get_supabase().table("leadoff_predictions").insert({
            "client_id": client_id,
            "city_id": brief.get("city_id"),
            "category_id": brief.get("category_id"),
            "category": brief.get("category"),
            "city_name": brief.get("city_name"),
            "state_code": brief.get("state_code"),
            "as_of": brief.get("as_of"),
            "assumptions": {"capture": capture, "lead_tier": lead_tier,
                            "lead_value_used": lead_value},
            "predicted": predicted,
            "competitors": brief.get("competitors") or [],
            "enrichment": brief.get("enrichment"),
            "proximity": ({"opportunity": proximity.get("opportunity"),
                           "underserved": proximity.get("underserved"),
                           "placement": proximity.get("placement"),
                           "pins_used": proximity.get("pins_used")}
                          if proximity and proximity.get("available") else None),
            "model_version": MODEL_VERSION,
            "created_by": user_id,
        }).execute().data[0]
        return row["id"]
    except Exception as exc:
        logger.warning("leadoff_calibration.capture_failed", extra={
            "client_id": client_id, "error": str(exc)})
        return None


# ── Outcome gathering + the monthly sweep (DB reads only, $0) ─────────────────

def _gather_sources(supabase, prediction: dict[str, Any]) -> dict[str, Any]:
    from datetime import date as _date

    from config import settings
    from services import rank_status
    from services.gbp_service import rating_and_review_count

    client_id = str(prediction["client_id"])
    sources: dict[str, Any] = {}

    client = (supabase.table("clients").select("gbp")
              .eq("id", client_id).limit(1).execute().data or [None])[0]
    _, reviews = rating_and_review_count((client or {}).get("gbp"))
    sources["client_reviews"] = reviews

    comps = (supabase.table("client_competitors").select("place_id")
             .eq("client_id", client_id).eq("active", True).execute().data or [])
    place_ids = [c["place_id"] for c in comps if c.get("place_id")]
    counts: list[int] = []
    if place_ids:
        for row in (supabase.table("competitor_gbp_profiles")
                    .select("place_id, profile").in_("place_id", place_ids)
                    .execute().data or []):
            v = ((row.get("profile") or {}).get("gbp_review_count")
                 or (row.get("profile") or {}).get("review_count"))
            if v is not None:
                counts.append(int(v))
    sources["competitor_review_counts"] = counts

    scans = (supabase.table("maps_scans").select("id")
             .eq("client_id", client_id).eq("status", "complete")
             .order("completed_at", desc=True).limit(1).execute().data or [])
    if scans:
        results = (supabase.table("maps_scan_results")
                   .select("keyword, top3_pins, total_pins")
                   .eq("scan_id", scans[0]["id"]).execute().data or [])
        share = maps_share(results, prediction.get("category") or "")
        sources["maps_top3_share"] = share
        if share is None:
            sources["maps_reason"] = "no maps result for the category keyword"
    else:
        sources["maps_reason"] = "no completed maps scan"

    tracked = (supabase.table("tracked_keywords").select("id, keyword")
               .eq("client_id", client_id).eq("active", True).execute().data or [])
    kw = match_keyword(tracked, prediction.get("category") or "",
                       prediction.get("city_name") or "")
    if kw:
        cutoff = _date.fromordinal(_date.today().toordinal() - 90).isoformat()
        rows = (supabase.table("rank_keyword_metrics")
                .select("date, gsc_position, tracked_rank, clicks, impressions")
                .eq("keyword_id", kw["id"]).gte("date", cutoff).execute().data or [])
        s = rank_status.compute_keyword_summary(rows, _date.today(),
                                                settings.rank_gsc_coverage_days)
        pos = s.get("avg_7") if s.get("primary_source") == "gsc" else s.get("today_rank")
        sources["organic_position"] = float(pos) if pos is not None else None
        if pos is None:
            sources["organic_reason"] = f"tracked keyword '{kw['keyword']}' has no rank data yet"
    else:
        sources["organic_reason"] = "no tracked keyword matches the market (manual tracking — owner ruling)"
    return sources


def run_calibration_sweep() -> None:
    """Daily scheduler tick; appends at most one check per prediction per
    CHECK_SPACING_DAYS. Best-effort per prediction; DB reads only."""
    from config import settings

    if not settings.leadoff_calibration_enabled:
        return
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    try:
        predictions = (supabase.table("leadoff_predictions").select("*")
                       .execute().data or [])
    except Exception as exc:
        logger.warning("leadoff_calibration.sweep_read_failed", extra={"error": str(exc)})
        return
    for p in predictions:
        try:
            last = (supabase.table("leadoff_outcome_checks")
                    .select("checked_at").eq("prediction_id", p["id"])
                    .order("checked_at", desc=True).limit(1).execute().data or [])
            if last:
                last_at = datetime.fromisoformat(
                    str(last[0]["checked_at"]).replace("Z", "+00:00"))
                if (now - last_at).days < CHECK_SPACING_DAYS:
                    continue
            built = build_outcome(p, _gather_sources(supabase, p), now)
            supabase.table("leadoff_outcome_checks").insert({
                "prediction_id": p["id"],
                "months_elapsed": built["months_elapsed"],
                "outcome": built["outcome"],
                "errors": built["errors"],
                "coverage": built["coverage"],
            }).execute()
        except Exception as exc:
            logger.warning("leadoff_calibration.check_failed", extra={
                "prediction_id": p.get("id"), "error": str(exc)})


def record_manual_leads(prediction_id: str, leads: float) -> dict[str, Any]:
    """Operator-entered monthly lead count (§3.3 path 1) — its own append-only
    check row, labeled manual; never conflated with automatic sources."""
    supabase = get_supabase()
    p = (supabase.table("leadoff_predictions").select("id, created_at, predicted")
         .eq("id", prediction_id).limit(1).execute().data or [None])[0]
    if p is None:
        raise LookupError("prediction_not_found")
    now = datetime.now(timezone.utc)
    exp = (p.get("predicted") or {}).get("exp_leads_mo")
    errors = {}
    if exp is not None:
        errors["leads_error"] = round(float(leads) - float(exp), 1)
    return supabase.table("leadoff_outcome_checks").insert({
        "prediction_id": prediction_id,
        "months_elapsed": months_elapsed(
            datetime.fromisoformat(str(p["created_at"]).replace("Z", "+00:00")), now),
        "outcome": {"note": "manual lead entry"},
        "errors": errors,
        "coverage": {},
        "actual_leads_mo": leads,
        "leads_source": "manual",
    }).execute().data[0]


def calibration_report() -> dict[str, Any]:
    supabase = get_supabase()
    predictions = (supabase.table("leadoff_predictions").select("*")
                   .order("created_at", desc=True).execute().data or [])
    checks: dict[str, list] = {}
    if predictions:
        for c in (supabase.table("leadoff_outcome_checks").select("*")
                  .in_("prediction_id", [p["id"] for p in predictions])
                  .execute().data or []):
            checks.setdefault(c["prediction_id"], []).append(c)
    return summarize(predictions, checks)
