"""Intervention-outcome loop — the measurement half of SerMaStr's decide+assign
flow (docs/modules/seo-strategist-agent-plan-v1_0.md, plan-review handoff).

PR #862 closed "decide + assign": the monthly strategist plan-review proposes
task additions, a human approves, and PACE assigns them capacity-aware. This
module closes "did it work" — for the goal-linked, MEASURABLE tactics only
(link-building + reoptimization proposals/tasks that target a campaign goal):

  1. **Registration** — when a goal-linked, in-scope proposal is *approved*
     (``register_from_proposal``, called from routers/strategist.py after
     ``asana_push.push_proposal``) OR its native task reaches a done status
     (``on_task_done``, called from task_service), an ``interventions`` row is
     inserted with the target metric's baseline snapshotted. Idempotent per a
     shared ``source_ref`` — whichever hook fires first creates the row; the
     other no-ops.
  2. **Evaluation** — ``run_intervention_sync`` (daily on gsc_scheduler, gated
     on ``intervention_tracking_enabled``) rechecks each open intervention at
     +2 weeks (interim, recorded) and +6 weeks (final verdict): the current
     metric vs the applied-at baseline → ``worked`` / ``partial`` / ``no_effect``.
  3. **Surfacing** — ``effectiveness`` rolls verdicts up per tactic_type so the
     strategy digest (``_prov_intervention_outcomes``) can tell the monthly
     plan-review "reoptimization moved 3/4 keywords; link-building 1/5". v1 is
     **report-only**: the strategist reads it, it does not auto-adjust proposals.

Legibility mirrors the rest of the strategist stack: the verdict is computed
HERE deterministically (the LLM never judges effectiveness), measurement reuses
each goal's canonical read (``campaign_goals.measure_goal``), and the pure
helpers (``classify_verdict``, ``evaluate_intervention``, ``summarize_effectiveness``,
``resolve_direction``) are unit-tested without a DB.

Everything is gated on ``settings.intervention_tracking_enabled`` (default
FALSE — ships dark). Registration hooks are best-effort — the loop must never
break an approval or a board write.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# The v1 in-scope tactics: measurable, goal-linked work. A proposal/task whose
# target declares anything else is ignored (no intervention registered).
TACTIC_TYPES = ("link_building", "reoptimization")

CHECK_INTERVAL_DAYS = 14   # first interim recheck ("expect movement ~2 weeks")
FINAL_DAYS = 42            # the 6-week mark — the verdict is committed here

# Verdict thresholds. Positions are absolute ranks (lower is better); other
# metrics (clicks, impressions, visibility %, pack presence %) are judged by
# relative gain.
WORKED_MIN_POSITIONS = 3.0
PARTIAL_MIN_POSITIONS = 1.0
WORKED_MIN_RELATIVE = 0.15   # +15% on a higher-is-better metric
PARTIAL_MIN_RELATIVE = 0.02  # any real upward move

# goal_type → measurement direction. Mirrors campaign_goals.LOWER_IS_BETTER.
_LOWER_IS_BETTER_TYPES = {"keyword_position"}


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def resolve_direction(goal_type: Optional[str]) -> str:
    """'lower_is_better' | 'higher_is_better' for a measured metric. Pure.

    keyword_position is the only lower-is-better goal metric; everything else
    (clicks / impressions / visibility / pack presence) is higher-is-better.
    Absent/custom goal_type defaults to keyword_position semantics (the tactic
    scope's default target is a keyword's rank)."""
    gt = goal_type or "keyword_position"
    return "lower_is_better" if gt in _LOWER_IS_BETTER_TYPES else "higher_is_better"


def classify_verdict(
    baseline: Optional[float],
    current: Optional[float],
    direction: str,
    *,
    target_value: Optional[float] = None,
) -> Optional[str]:
    """'worked' | 'partial' | 'no_effect' from baseline→current. Pure.

    None when it can't be judged (either value missing). A met explicit target
    is always 'worked'. Otherwise:
      * lower_is_better (rank): improvement = baseline − current positions.
      * higher_is_better: improvement = relative gain (current − baseline)/baseline
        (falls back to an absolute-move test when baseline is 0)."""
    if baseline is None or current is None:
        return None
    b, c = float(baseline), float(current)
    if direction == "lower_is_better":
        if target_value is not None and c <= float(target_value):
            return "worked"
        gain = b - c
        if gain >= WORKED_MIN_POSITIONS:
            return "worked"
        if gain >= PARTIAL_MIN_POSITIONS:
            return "partial"
        return "no_effect"
    # higher_is_better
    if target_value is not None and c >= float(target_value):
        return "worked"
    if b == 0:
        # No baseline mass — any positive value is a partial move, a big one worked.
        if c <= 0:
            return "no_effect"
        return "worked" if c >= 1 else "partial"
    rel = (c - b) / abs(b)
    if rel >= WORKED_MIN_RELATIVE:
        return "worked"
    if rel >= PARTIAL_MIN_RELATIVE:
        return "partial"
    return "no_effect"


def evaluate_intervention(
    intervention: dict, current_value: Optional[float], now: datetime
) -> dict:
    """Decide one due-check's outcome. Pure.

    Returns ``{verdict, is_final, due}`` — ``verdict`` is the provisional/final
    classification ('worked'|'partial'|'no_effect'|None) and ``is_final`` says
    whether the 6-week mark has passed (the caller commits ``verdict`` only
    then; before that the check is recorded but the row stays open so a slow
    responder can still recover)."""
    applied = _parse_ts(intervention.get("applied_at"))
    age_days = (now - applied).days if applied else 0
    due = age_days >= CHECK_INTERVAL_DAYS
    baseline = (intervention.get("baseline") or {}).get("value")
    direction = (intervention.get("baseline") or {}).get("direction") or resolve_direction(
        (intervention.get("target") or {}).get("goal_type")
    )
    target_value = (intervention.get("target") or {}).get("target_value")
    verdict = classify_verdict(baseline, current_value, direction, target_value=target_value)
    return {"verdict": verdict, "is_final": age_days >= FINAL_DAYS, "due": due, "age_days": age_days}


def summarize_effectiveness(interventions: list[dict]) -> dict:
    """Per-tactic-type effectiveness rollup for the digest. Pure.

    ``{by_tactic: {tactic: {worked, partial, no_effect, pending, total}},
       overall: {...}, note}``. A row with no committed verdict yet counts as
    ``pending`` (measured, but before its 6-week mark, or unmeasurable)."""
    def _blank() -> dict:
        return {"worked": 0, "partial": 0, "no_effect": 0, "pending": 0, "total": 0}

    by_tactic: dict[str, dict] = {}
    overall = _blank()
    for iv in interventions or []:
        tactic = iv.get("tactic_type") or "other"
        bucket = by_tactic.setdefault(tactic, _blank())
        verdict = iv.get("verdict")
        key = verdict if verdict in ("worked", "partial", "no_effect") else "pending"
        bucket[key] += 1
        bucket["total"] += 1
        overall[key] += 1
        overall["total"] += 1
    return {
        "by_tactic": by_tactic,
        "overall": overall,
        "note": (
            "Effectiveness of goal-linked link-building / reoptimization work: did "
            "the metric each intervention targeted actually move by its 6-week mark. "
            "'worked' = clear improvement, 'partial' = some, 'no_effect' = none, "
            "'pending' = not yet at its verdict mark (or not measurable). Report-only "
            "in v1 — read it, cite it; it does not auto-adjust anything."
        ),
    }


def proposal_target(proposal: dict) -> Optional[dict]:
    """The sanitized ``target`` off a proposal, or None. Pure.

    A target is honored only when it names an in-scope tactic AND at least one
    concrete anchor (keyword or page_url). Anything else → None, so the proposal
    behaves exactly as an untargeted one (no intervention)."""
    if not isinstance(proposal, dict):
        return None
    target = proposal.get("target")
    if not isinstance(target, dict):
        return None
    tactic = target.get("tactic_type")
    if tactic not in TACTIC_TYPES:
        return None
    keyword = (target.get("keyword") or "").strip()
    page_url = (target.get("page_url") or "").strip()
    if not (keyword or page_url):
        return None
    return {"tactic_type": tactic, "keyword": keyword or None, "page_url": page_url or None}


# ─────────────────────────────────────────────────────────────────────────────
# Measurement (reuses campaign_goals' canonical reads)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_goal(supabase, client_id: str, keyword: Optional[str]) -> Optional[dict]:
    """The client's campaign_goal that best matches an intervention target's
    keyword — prefers a keyword_position goal on that exact keyword. None when
    nothing matches (the intervention still registers, goal_id null)."""
    if not keyword:
        return None
    wanted = keyword.strip().casefold()
    try:
        goals = (
            supabase.table("campaign_goals")
            .select("*")
            .eq("client_id", client_id).eq("active", True)
            .execute()
        ).data or []
    except Exception:
        return None
    matches = [
        g for g in goals
        if (g.get("keyword") or "").strip().casefold() == wanted
    ]
    if not matches:
        return None
    # Prefer a keyword_position goal (the direct rank yardstick).
    matches.sort(key=lambda g: 0 if g.get("goal_type") == "keyword_position" else 1)
    return matches[0]


def _resolve_keyword_id(supabase, client_id: str, keyword: Optional[str]) -> Optional[str]:
    if not keyword:
        return None
    wanted = keyword.strip().casefold()
    try:
        rows = (
            supabase.table("tracked_keywords")
            .select("id, keyword")
            .eq("client_id", client_id).eq("active", True)
            .execute()
        ).data or []
    except Exception:
        return None
    match = next((r for r in rows if (r.get("keyword") or "").strip().casefold() == wanted), None)
    return match["id"] if match else None


def _measure(supabase, client_id: str, goal: Optional[dict], keyword: Optional[str],
             today: date) -> tuple[Optional[float], str, str]:
    """(value, metric, direction) for an intervention target. Reuses
    ``campaign_goals.measure_goal`` so the loop reads exactly what the goal
    itself reads; when no goal is linked, measures the target keyword's rank
    position (the tactic scope's default metric)."""
    from services import campaign_goals

    meas_goal = goal or {"goal_type": "keyword_position", "keyword": keyword}
    goal_type = meas_goal.get("goal_type") or "keyword_position"
    direction = resolve_direction(goal_type)
    value: Optional[float] = None
    try:
        value = campaign_goals.measure_goal(supabase, client_id, meas_goal, today)
    except Exception as exc:
        logger.warning(
            "interventions.measure_failed",
            extra={"client_id": client_id, "goal_type": goal_type, "error": str(exc)},
        )
    return value, goal_type, direction


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────
def _register(client_id: str, source: str, source_ref: str, tactic_type: str,
              target: dict) -> Optional[str]:
    """Insert one intervention, snapshotting the baseline. Idempotent on
    ``source_ref`` (a duplicate returns the existing id). Best-effort — never
    raises into the calling hook. No-op while the flag is off."""
    if not settings.intervention_tracking_enabled:
        return None
    if tactic_type not in TACTIC_TYPES:
        return None
    supabase = get_supabase()
    # Idempotency: a row already keyed to this source_ref wins.
    try:
        existing = (
            supabase.table("interventions").select("id")
            .eq("source_ref", source_ref).limit(1).execute()
        ).data
        if existing:
            return existing[0]["id"]
    except Exception as exc:
        logger.warning("interventions.dedup_read_failed", extra={"source_ref": source_ref, "error": str(exc)})
        return None

    today = date.today()
    now = datetime.now(timezone.utc)
    keyword = target.get("keyword")
    goal = _resolve_goal(supabase, client_id, keyword)
    keyword_id = _resolve_keyword_id(supabase, client_id, keyword)
    value, goal_type, direction = _measure(supabase, client_id, goal, keyword, today)

    target_value = None
    if goal:
        target_value = goal.get("target_value")
        if target_value is None and goal.get("goal_type") == "keyword_position":
            target_value = goal.get("target_position")

    row = {
        "client_id": client_id,
        "source": source,
        "source_ref": source_ref,
        "tactic_type": tactic_type,
        "goal_id": goal.get("id") if goal else None,
        "target": {
            "keyword": keyword,
            "keyword_id": keyword_id,
            "page_url": target.get("page_url"),
            "goal_type": goal_type,
            "target_value": target_value,
        },
        "baseline": {
            "value": value,
            "metric": goal_type,
            "direction": direction,
            "measured_at": now.isoformat(),
        },
        "applied_at": now.isoformat(),
        "next_check_at": (now + timedelta(days=CHECK_INTERVAL_DAYS)).isoformat(),
    }
    try:
        inserted = supabase.table("interventions").insert(row).execute().data
        iid = inserted[0]["id"] if inserted else None
        logger.info(
            "interventions.registered",
            extra={"client_id": client_id, "source": source, "tactic": tactic_type,
                   "goal_linked": bool(goal), "baseline": value},
        )
        return iid
    except Exception as exc:
        # A concurrent insert may have won the unique(source_ref) race — treat a
        # duplicate as success (idempotent), everything else as a best-effort miss.
        try:
            existing = (
                supabase.table("interventions").select("id")
                .eq("source_ref", source_ref).limit(1).execute()
            ).data
            if existing:
                return existing[0]["id"]
        except Exception:
            pass
        logger.warning("interventions.insert_failed", extra={"source_ref": source_ref, "error": str(exc)})
        return None


def source_ref_for_proposal(review_id: str, idx: int) -> str:
    """The shared idempotency key both registration hooks use for one proposal."""
    return f"strategy_proposal:{review_id}:{idx}"


def register_from_proposal(client_id: str, review_id: str, idx: int,
                           proposal: dict) -> Optional[str]:
    """Register an intervention for a just-approved strategist proposal. Called
    from the proposal-approve endpoint after the task is pushed. Best-effort;
    returns the intervention id (or None when out of scope / disabled)."""
    target = proposal_target(proposal)
    if not target:
        return None
    return _register(
        client_id,
        source="strategy_proposal",
        source_ref=source_ref_for_proposal(review_id, idx),
        tactic_type=target["tactic_type"],
        target=target,
    )


def on_task_done(task: dict) -> Optional[str]:
    """Register (idempotently) when a native task carrying an intervention
    ``target`` reaches a done status. The task-shape carrier is
    ``tasks.target`` (stamped by asana_push.push_proposal from the proposal's
    target). Shares the proposal's source_ref when present, so this and the
    approval hook converge on ONE row. Best-effort — never raises into
    task_service."""
    try:
        if not settings.intervention_tracking_enabled:
            return None
        if not isinstance(task, dict):
            return None
        target = task.get("target")
        if not isinstance(target, dict):
            return None
        tactic = target.get("tactic_type")
        if tactic not in TACTIC_TYPES:
            return None
        if not ((target.get("keyword") or "").strip() or (target.get("page_url") or "").strip()):
            return None
        client_id = task.get("client_id")
        if not client_id:
            return None
        source_ref = target.get("source_ref") or f"native_task:{task.get('id')}"
        return _register(
            client_id,
            source="native_task",
            source_ref=source_ref,
            tactic_type=tactic,
            target={
                "tactic_type": tactic,
                "keyword": (target.get("keyword") or "").strip() or None,
                "page_url": (target.get("page_url") or "").strip() or None,
            },
        )
    except Exception as exc:
        logger.warning("interventions.on_task_done_failed", extra={"task_id": task.get("id"), "error": str(exc)})
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Daily evaluator sweep (shared scheduler)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_check(supabase, iv: dict, result: dict, current_value: Optional[float],
                 now: datetime) -> None:
    checks = list(iv.get("checks") or [])
    checks.append({
        "at": now.isoformat(),
        "verdict": result["verdict"],
        "value": current_value,
        "age_days": result.get("age_days"),
    })
    updates: dict = {"checks": checks, "updated_at": now.isoformat()}
    if result["is_final"]:
        # Commit the verdict and close the intervention.
        updates.update({
            "verdict": result["verdict"] or "no_effect",
            "evaluated_at": now.isoformat(),
            "next_check_at": None,
        })
    else:
        updates["next_check_at"] = (now + timedelta(days=CHECK_INTERVAL_DAYS)).isoformat()
    supabase.table("interventions").update(updates).eq("id", iv["id"]).execute()


def run_intervention_sync() -> dict:
    """Daily sweep: recheck each open (unverified) intervention that is due,
    committing a verdict at its 6-week mark. Best-effort per row — one bad row
    never stops the sweep. No-op while the flag is off."""
    stats = {"checked": 0, "worked": 0, "partial": 0, "no_effect": 0, "final": 0}
    if not settings.intervention_tracking_enabled:
        return stats
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    today = now.date()
    try:
        rows = (
            supabase.table("interventions").select("*")
            .is_("verdict", "null")
            .lte("next_check_at", now.isoformat())
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("interventions.sync_read_failed", extra={"error": str(exc)})
        return stats

    for iv in rows:
        try:
            goal = None
            goal_id = iv.get("goal_id")
            if goal_id:
                g = (
                    supabase.table("campaign_goals").select("*")
                    .eq("id", goal_id).limit(1).execute()
                ).data
                goal = g[0] if g else None
            keyword = (iv.get("target") or {}).get("keyword")
            current, _, _ = _measure(supabase, iv["client_id"], goal, keyword, today)
            result = evaluate_intervention(iv, current, now)
            if not result["due"]:
                continue
            _apply_check(supabase, iv, result, current, now)
            stats["checked"] += 1
            if result["is_final"]:
                stats["final"] += 1
                verdict = result["verdict"] or "no_effect"
                if verdict in stats:
                    stats[verdict] += 1
        except Exception as exc:
            logger.warning("interventions.check_failed", extra={"intervention_id": iv.get("id"), "error": str(exc)})

    if any(stats.values()):
        logger.info("interventions.sync_complete", extra=stats)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Reads (API + digest provider)
# ─────────────────────────────────────────────────────────────────────────────
def list_interventions(client_id: str, limit: int = 100) -> list[dict]:
    """A client's interventions, newest first. Best-effort ([] on failure)."""
    try:
        return (
            get_supabase().table("interventions").select("*")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(max(1, min(limit, 500)))
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("interventions.list_failed", extra={"client_id": client_id, "error": str(exc)})
        return []


def effectiveness(client_id: str) -> dict:
    """The per-tactic effectiveness rollup for one client (report surface)."""
    return summarize_effectiveness(list_interventions(client_id))
