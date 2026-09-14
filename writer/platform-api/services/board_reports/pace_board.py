"""PACE board report — VP of Delivery & Operations to the L10 board.

Owns: does committed work ship, on time, at sustainable capacity. Reuses the
tested `pace_report` delivery aggregations + `task_workload` (real Everhour
utilization when present, else estimate). Dollar margin is deferred until a
loaded hourly cost is configured (see docs/modules/board-reports-plan-v1_0.md).

Pure assembly (`build_scorecard`/`verdict_for`/`build_report`) is unit-tested;
`run` does the I/O + emit.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase
from services.board_reports import common

logger = logging.getLogger(__name__)


def _completed_between(start: date, end: date) -> int:
    """Count completed top-level tasks with ``completed_at`` in [start, end),
    excluding Asana-import artifacts. Best-effort (0 on error)."""
    from services import pace_report

    try:
        rows = (
            get_supabase().table("tasks")
            .select("completed_at, created_at, source")
            .eq("completed", True).is_("deleted_at", "null").is_("parent_task_id", "null")
            .gte("completed_at", start.isoformat()).lt("completed_at", end.isoformat())
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("board_reports.pace_prev_week_failed", extra={"error": str(exc)})
        return 0
    return sum(1 for r in rows if not pace_report.is_import_stamped(r))


def verdict_for(*, overloaded: int, behind_pace: int, overdue: int, stuck: int,
                unassigned: int, unacted: int) -> tuple[str, str]:
    """(rag, verdict sentence) from the delivery signals. Pure."""
    if overloaded or behind_pace:
        bits = []
        if overloaded:
            bits.append(f"{overloaded} over capacity")
        if behind_pace:
            bits.append(f"{behind_pace} clients behind pace")
        return "red", "Delivery under strain — " + ", ".join(bits) + "."
    if overdue or stuck or unassigned or unacted:
        return "yellow", (
            f"Delivery holding, with {overdue} overdue and {stuck} stuck to clear."
        )
    return "green", "Delivery on track — nothing overdue, stuck, or over capacity."


def build_report(today: date, *, rep: dict, prev_completed: int, workload: dict) -> dict:
    """Assemble the PACE board report from the delivery report + workload. Pure."""
    completed = rep.get("completed_count", 0)
    overdue = rep.get("overdue", 0)
    stuck = rep.get("stuck", 0)
    unassigned = rep.get("unassigned", 0)
    unacted = rep.get("unacted", 0)
    behind_pace = rep.get("behind_pace", 0)

    members = workload.get("members") or []
    overloaded = [m for m in members if m.get("overloaded")]
    logged = [m["utilization_pct"] for m in members if m.get("utilization_pct") is not None]
    real_util = round(sum(logged) / len(logged)) if logged else None
    open_hours = sum((m.get("open_hours") or 0) for m in members)
    capacity = sum((m.get("weekly_hours") or 0) for m in members)

    rag, verdict = verdict_for(
        overloaded=len(overloaded), behind_pace=behind_pace, overdue=overdue,
        stuck=stuck, unassigned=unassigned, unacted=unacted,
    )

    util_value = f"{real_util}%" if real_util is not None else "n/a"
    util_basis = "logged" if logged else "estimate"
    scorecard = [
        {"label": "Completed (7d)", "value": str(completed),
         "delta": common.pct_delta(completed, prev_completed)},
        {"label": "Overdue", "value": str(overdue)},
        {"label": "Stuck / blocked", "value": str(stuck)},
        {"label": "Unassigned", "value": str(unassigned)},
        {"label": "Clients behind pace", "value": str(behind_pace)},
        {"label": f"Team utilization ({util_basis})", "value": util_value},
        {"label": "Over capacity", "value": str(len(overloaded))},
    ]

    wins: list[str] = []
    by_person = rep.get("throughput_by_person") or {}
    if by_person:
        top_person, n = next(iter(by_person.items()))
        wins.append(f"{top_person} shipped {n} task{'s' if n != 1 else ''} this week.")
    by_cat = rep.get("throughput_by_category") or {}
    if by_cat:
        top_cat, n = next(iter(by_cat.items()))
        wins.append(f"Most output was {top_cat} ({n}).")
    if prev_completed and completed > prev_completed:
        wins.append(f"Throughput up vs last week ({prev_completed} → {completed}).")

    risks: list[dict] = []
    for m in overloaded[:5]:
        risks.append({
            "issue": f"{m.get('name') or m.get('gid')} over capacity",
            "severity": "capacity", "owner": m.get("name") or m.get("gid"),
            "action": "rebalance load or add capacity",
        })
    if behind_pace:
        risks.append({
            "issue": f"{behind_pace} client{'s' if behind_pace != 1 else ''} behind the monthly plan",
            "action": "review plans / re-scope this week",
        })
    if overdue >= 5:
        risks.append({"issue": f"{overdue} tasks overdue", "action": "triage and re-date"})
    if stuck:
        risks.append({"issue": f"{stuck} tasks blocked/stale", "action": "unblock or reassign"})

    asks: list[str] = []
    if overloaded:
        names = ", ".join((m.get("name") or m.get("gid")) for m in overloaded[:5])
        asks.append(f"Approve capacity for {names}, or agree what to deprioritize.")

    outlook = None
    if capacity:
        outlook = (
            f"~{round(open_hours)}h of committed work queued against ~{round(capacity)}h/wk "
            f"of team capacity."
        )

    report = {
        "agent": "PACE",
        "title": f"PACE delivery board report · week of {common.monday_of(today).isoformat()}",
        "verdict": verdict, "rag": rag, "as_of": today.isoformat(),
        "scorecard": scorecard, "wins": wins, "risks": risks, "asks": asks,
        "outlook": outlook,
    }
    return report


def run(today: Optional[date] = None) -> dict:
    """Build + emit the PACE board report. Best-effort."""
    from services import pace_report, task_workload

    today = today or date.today()
    rep = pace_report.build_report(None, today=today, period_days=7)
    prev_completed = _completed_between(today - timedelta(days=14), today - timedelta(days=7))
    workload = task_workload.build_team_workload()
    report = build_report(today, rep=rep, prev_completed=prev_completed, workload=workload)
    common.attach_narrative(report, "PACE, the VP of Delivery & Operations")
    return common.emit_report(report, kind="pace_board_report", today=today, link="/workload")
