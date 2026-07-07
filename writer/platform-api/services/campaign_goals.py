"""Campaign goals — per-client success targets + deterministic progress reads.

The strategist layer (digest, Slack answers, reviews) needs to know what
success MEANS for a client before it can judge "on track / behind" or forecast
against anything. A goal is a target on one of the suite's own metrics
("<keyword> to top 3 by Q4", "800 organic clicks/mo", "60% AI visibility"),
with the baseline captured at creation.

Legibility rules (same as the rest of the strategist stack):
  * status is computed HERE, deterministically, on read — the LLM never does
    the arithmetic and nothing stale is stored (only `achieved_at`, a record
    of first achievement, is persisted).
  * measurement reuses each module's own canonical read (rank_status weighted
    positions, GSC daily sums, brand trend rollups, geo-grid top-3 share) —
    no new data capture, no paid calls.

Split: `evaluate_goal`/`progress_fraction`/`goal_note` are pure and
unit-tested; `measure_goal`/`assess_goals` do DB reads (each goal isolated —
one unmeasurable goal never breaks the assessment).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# goal_type → direction of "better" for the measured value.
LOWER_IS_BETTER = {"keyword_position"}
GOAL_TYPES = (
    "keyword_position",
    "keywords_in_top",
    "organic_clicks",
    "organic_impressions",
    "ai_visibility",
    "maps_pack_presence",
    "custom",
)

# On-pace grace: progress may trail elapsed time by this fraction before the
# goal reads "behind" (movement is lumpy — links index in waves).
_PACE_GRACE = 0.15
_CLICKS_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Pure evaluation (unit-tested)
# ---------------------------------------------------------------------------
def progress_fraction(
    baseline: Optional[float], current: Optional[float], target: Optional[float],
    lower_is_better: bool,
) -> Optional[float]:
    """How far from baseline toward target we've moved, clamped to [0, 1].

    None when it can't be computed (missing values, or baseline already at /
    past the target — nothing to progress through). Pure."""
    if baseline is None or current is None or target is None:
        return None
    span = (baseline - target) if lower_is_better else (target - baseline)
    if span <= 0:
        return None
    moved = (baseline - current) if lower_is_better else (current - baseline)
    return max(0.0, min(1.0, moved / span))


def _target_met(current: Optional[float], target: Optional[float], lower_is_better: bool) -> bool:
    if current is None or target is None:
        return False
    return current <= target if lower_is_better else current >= target


def evaluate_goal(goal: dict, current_value: Optional[float], today: date) -> dict:
    """Deterministic status for one goal given its freshly measured value. Pure.

    Returns {status, progress_pct, elapsed_pct} — status one of:
      achieved | on_track | behind | overdue | no_data | manual
    Pace uses the time axis only when a due date exists: progress% must keep
    within _PACE_GRACE of elapsed%. Without a due date any movement toward the
    target reads on_track.
    """
    if goal.get("goal_type") == "custom":
        return {"status": "manual", "progress_pct": None, "elapsed_pct": None}
    lower = goal.get("goal_type") in LOWER_IS_BETTER
    target = goal.get("target_value")
    if _target_met(current_value, target, lower):
        return {"status": "achieved", "progress_pct": 100.0, "elapsed_pct": None}
    if current_value is None:
        return {"status": "no_data", "progress_pct": None, "elapsed_pct": None}

    progress = progress_fraction(goal.get("baseline_value"), current_value, target, lower)
    progress_pct = round(progress * 100.0, 1) if progress is not None else None

    due = _parse_date(goal.get("due_date"))
    start = _parse_date(goal.get("baseline_date")) or _parse_date(goal.get("created_at"))
    if due:
        if today > due:
            return {"status": "overdue", "progress_pct": progress_pct, "elapsed_pct": 100.0}
        elapsed_pct = None
        if start and due > start:
            elapsed = (today - start).days / (due - start).days
            elapsed_pct = round(min(1.0, max(0.0, elapsed)) * 100.0, 1)
            if progress is not None:
                status = "on_track" if progress >= (elapsed - _PACE_GRACE) else "behind"
                return {"status": status, "progress_pct": progress_pct, "elapsed_pct": elapsed_pct}
        # No usable pace axis → judge by movement alone.
        return {
            "status": "on_track" if (progress or 0) > 0 else "behind",
            "progress_pct": progress_pct,
            "elapsed_pct": elapsed_pct,
        }
    return {
        "status": "on_track" if (progress or 0) > 0 else "behind",
        "progress_pct": progress_pct,
        "elapsed_pct": None,
    }


def goal_note(goal: dict, evaluation: dict, current_value: Optional[float]) -> str:
    """One-line human/LLM-readable progress note. Pure."""
    label = goal.get("label") or goal.get("goal_type")
    status = evaluation.get("status")
    bits = [f"{label}: {status.upper()}" if status else str(label)]
    if current_value is not None:
        cur = f"{current_value:g}"
        tgt = goal.get("target_value")
        bits.append(f"now {cur}" + (f" vs target {tgt:g}" if tgt is not None else ""))
    if goal.get("baseline_value") is not None:
        bits.append(f"baseline {goal['baseline_value']:g}")
    if evaluation.get("progress_pct") is not None:
        pace = f"{evaluation['progress_pct']:g}% of the way"
        if evaluation.get("elapsed_pct") is not None:
            pace += f" with {evaluation['elapsed_pct']:g}% of the time used"
        bits.append(pace)
    if goal.get("due_date"):
        bits.append(f"due {goal['due_date']}")
    return " — ".join(bits)


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Measurement — reuses each module's canonical read. One function per type.
# ---------------------------------------------------------------------------
def _measure_keyword_position(supabase, client_id: str, goal: dict, today: date) -> Optional[float]:
    from config import settings
    from services import rank_status

    wanted = (goal.get("keyword") or "").strip().casefold()
    if not wanted:
        return None
    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id).eq("active", True).execute()
    ).data or []
    match = next((k for k in kws if (k.get("keyword") or "").strip().casefold() == wanted), None)
    if not match:
        return None
    cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
    rows = (
        supabase.table("rank_keyword_metrics")
        .select("date, gsc_position, tracked_rank, clicks, impressions")
        .eq("keyword_id", match["id"]).gte("date", cutoff).execute()
    ).data or []
    s = rank_status.compute_keyword_summary(rows, today, settings.rank_gsc_coverage_days)
    value = s.get("avg_7") if s.get("primary_source") == "gsc" else s.get("today_rank")
    return float(value) if value is not None else None


def _measure_keywords_in_top(supabase, client_id: str, goal: dict, today: date) -> Optional[float]:
    from config import settings
    from services import rank_status

    top_n = goal.get("target_position")
    if not top_n:
        return None
    kws = (
        supabase.table("tracked_keywords")
        .select("id").eq("client_id", client_id).eq("active", True).execute()
    ).data or []
    if not kws:
        return None
    kw_ids = [k["id"] for k in kws]
    cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
    metrics: dict[str, list[dict]] = {}
    for r in (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position, tracked_rank, clicks, impressions")
        .in_("keyword_id", kw_ids).gte("date", cutoff).execute()
    ).data or []:
        metrics.setdefault(r["keyword_id"], []).append(r)
    count = 0
    for kid in kw_ids:
        s = rank_status.compute_keyword_summary(metrics.get(kid, []), today, settings.rank_gsc_coverage_days)
        value = s.get("avg_7") if s.get("primary_source") == "gsc" else s.get("today_rank")
        if value is not None and value <= top_n:
            count += 1
    return float(count)


def _measure_gsc_sum(supabase, client_id: str, field: str, today: date) -> Optional[float]:
    prop = (
        supabase.table("gsc_properties")
        .select("id").eq("client_id", client_id).eq("access_status", "ok")
        .limit(1).execute()
    ).data
    if not prop:
        return None
    cutoff = date.fromordinal(today.toordinal() - _CLICKS_WINDOW_DAYS).isoformat()
    rows = (
        supabase.table("gsc_query_daily")
        .select(field)
        .eq("property_id", prop[0]["id"]).gte("date", cutoff).execute()
    ).data or []
    if not rows:
        return None
    return float(sum(r.get(field) or 0 for r in rows))


def _measure_ai_visibility(supabase, client_id: str, goal: dict, today: date) -> Optional[float]:
    from services import brand_service

    trends = brand_service.get_trends(client_id)
    if not trends:
        return None
    value = trends[-1].get("visibility_pct")
    return float(value) if value is not None else None


def _measure_maps_pack(supabase, client_id: str, goal: dict, today: date) -> Optional[float]:
    scans = (
        supabase.table("maps_scans")
        .select("id").eq("client_id", client_id).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data
    if not scans:
        return None
    results = (
        supabase.table("maps_scan_results")
        .select("top3_pins, total_pins")
        .eq("scan_id", scans[0]["id"]).execute()
    ).data or []
    total = sum(r.get("total_pins") or 0 for r in results)
    top3 = sum(r.get("top3_pins") or 0 for r in results)
    return round(100.0 * top3 / total, 1) if total else None


def measure_goal(supabase, client_id: str, goal: dict, today: date) -> Optional[float]:
    """Current value for one goal from the owning module's canonical read."""
    goal_type = goal.get("goal_type")
    if goal_type == "keyword_position":
        return _measure_keyword_position(supabase, client_id, goal, today)
    if goal_type == "keywords_in_top":
        return _measure_keywords_in_top(supabase, client_id, goal, today)
    if goal_type == "organic_clicks":
        return _measure_gsc_sum(supabase, client_id, "clicks", today)
    if goal_type == "organic_impressions":
        return _measure_gsc_sum(supabase, client_id, "impressions", today)
    if goal_type == "ai_visibility":
        return _measure_ai_visibility(supabase, client_id, goal, today)
    if goal_type == "maps_pack_presence":
        return _measure_maps_pack(supabase, client_id, goal, today)
    return None  # custom


# ---------------------------------------------------------------------------
# Assessment (the read every surface uses)
# ---------------------------------------------------------------------------
def assess_goals(client_id: str, today: Optional[date] = None, include_inactive: bool = False) -> list[dict]:
    """All of a client's goals with freshly computed value/status/note.

    Each goal is isolated — a failing measurement yields status no_data for
    that goal, never an exception to the caller. Marks `achieved_at` (once)
    when a goal is first seen achieved."""
    supabase = get_supabase()
    today = today or date.today()
    q = (
        supabase.table("campaign_goals")
        .select("*").eq("client_id", client_id)
        .order("created_at", desc=False)
    )
    if not include_inactive:
        q = q.eq("active", True)
    goals = q.execute().data or []

    out: list[dict] = []
    for goal in goals:
        current: Optional[float] = None
        try:
            current = measure_goal(supabase, client_id, goal, today)
        except Exception as exc:
            logger.warning(
                "campaign_goals.measure_failed",
                extra={"client_id": client_id, "goal_id": goal.get("id"), "error": str(exc)},
            )
        evaluation = evaluate_goal(goal, current, today)
        if evaluation["status"] == "achieved" and not goal.get("achieved_at"):
            try:
                stamp = datetime.now(timezone.utc).isoformat()
                supabase.table("campaign_goals").update({"achieved_at": stamp}).eq(
                    "id", goal["id"]
                ).execute()
                goal["achieved_at"] = stamp
            except Exception:
                pass  # a missed stamp self-heals on the next read
        out.append({
            **goal,
            "current_value": current,
            **evaluation,
            "note": goal_note(goal, evaluation, current),
        })
    return out


def create_goal(client_id: str, fields: dict, created_by: Optional[str] = None) -> dict:
    """Insert a goal, capturing the current metric as its baseline."""
    supabase = get_supabase()
    today = date.today()
    baseline: Optional[float] = None
    try:
        baseline = measure_goal(supabase, client_id, fields, today)
    except Exception as exc:
        logger.warning(
            "campaign_goals.baseline_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
    row = {
        "client_id": client_id,
        "goal_type": fields.get("goal_type"),
        "label": fields.get("label"),
        "keyword": fields.get("keyword"),
        "target_value": fields.get("target_value"),
        "target_position": fields.get("target_position"),
        "due_date": fields.get("due_date"),
        "notes": fields.get("notes"),
        "baseline_value": baseline,
        "baseline_date": today.isoformat() if baseline is not None else None,
        "created_by": created_by,
    }
    return (supabase.table("campaign_goals").insert(row).execute()).data[0]
