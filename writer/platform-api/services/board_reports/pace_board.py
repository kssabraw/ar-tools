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


def _pace_cases(board: dict, names: dict, overloaded: list[dict]) -> list[dict]:
    """The who/what/why/how detail behind the delivery numbers: over-capacity
    people, the specific stuck + overdue tasks (with client + owner + days), and
    behind-pace clients. Pure."""
    items: list[dict] = []
    for m in overloaded[:5]:
        nm = m.get("name") or m.get("gid")
        bits = []
        if m.get("utilization_pct") is not None:
            bits.append(f"{m['utilization_pct']}% utilized")
        if m.get("weekly_hours"):
            bits.append(f"~{round(m.get('open_hours') or 0)}h committed vs {round(m['weekly_hours'])}h/wk capacity")
        items.append({
            "name": f"{nm} — over capacity", "rag": "red",
            "detail": [
                {"label": "Load", "text": "; ".join(bits) or "over capacity"},
                {"label": "Action", "text": "Rebalance load or add capacity."},
            ],
        })

    stuck, overdue, behind = [], [], []
    for c in (board.get("clients") or []):
        cname = names.get(c.get("client_id"), "Client")
        for s in c.get("stale", []):
            stuck.append((cname, s))
        for o in c.get("overdue", []):
            overdue.append((cname, o))
        if (c.get("month_pace") or {}).get("behind"):
            behind.append((cname, c["month_pace"]))
    stuck.sort(key=lambda x: -(x[1].get("days") or 0))

    for cname, s in stuck[:6]:
        status = s.get("status_key") or "in progress"
        if s.get("days") is not None:
            status = f"{status} for {s['days']}d"
        items.append({
            "name": s.get("name") or "Task", "rag": "yellow",
            "detail": [
                {"label": "Client", "text": cname},
                {"label": "Owner", "text": s.get("assignee_name") or "unassigned"},
                {"label": "Status", "text": f"Stuck — {status}"},
                {"label": "Action", "text": "Unblock or reassign."},
            ],
        })
    for cname, o in overdue[:4]:
        due = f"due {str(o.get('due_date'))[:10]}" if o.get("due_date") else "past due"
        items.append({
            "name": o.get("name") or "Task", "rag": "yellow",
            "detail": [
                {"label": "Client", "text": cname},
                {"label": "Owner", "text": o.get("assignee_name") or "unassigned"},
                {"label": "Status", "text": f"Overdue — {due}"},
                {"label": "Action", "text": "Triage and re-date."},
            ],
        })
    for cname, p in behind[:4]:
        if p.get("mode") == "due_weighted":
            nums = f"{round((p.get('actual') or 0) * 100)}% done vs {round((p.get('expected') or 0) * 100)}% expected by now"
        else:
            nums = (f"{round((p.get('pct_complete') or 0) * 100)}% done vs "
                    f"{round((p.get('pct_elapsed') or 0) * 100)}% of the month elapsed")
        items.append({
            "name": f"{cname} — behind pace", "rag": "red",
            "detail": [
                {"label": "Pace", "text": nums},
                {"label": "Action", "text": "Review the plan / re-scope this week."},
            ],
        })
    return items


def build_report(today: date, *, rep: dict, prev_completed: int, workload: dict,
                 board: Optional[dict] = None, names: Optional[dict] = None) -> dict:
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

    # The detail now lives in `cases` (named tasks/people); keep `risks` empty so
    # it isn't a redundant terse echo above the full write-ups.
    cases_items = _pace_cases(board or {}, names or {}, overloaded)
    risks: list[dict] = []

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
        "cases": {"title": "Delivery detail — stuck work, capacity, pace", "items": cases_items},
        "outlook": outlook,
    }
    return report


def _client_names(supabase, client_ids: list) -> dict:
    ids = [c for c in {c for c in client_ids if c}]
    if not ids:
        return {}
    try:
        rows = supabase.table("clients").select("id, name").in_("id", ids).execute().data or []
        return {r["id"]: r.get("name") or r["id"] for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("board_reports.pace_names_failed", extra={"error": str(exc)})
        return {}


def run(today: Optional[date] = None) -> dict:
    """Build + emit the PACE board report. Best-effort."""
    from services import pace_report, pm_signals, task_workload

    today = today or date.today()
    rep = pace_report.build_report(None, today=today, period_days=7)
    prev_completed = _completed_between(today - timedelta(days=14), today - timedelta(days=7))
    workload = task_workload.build_team_workload()
    board = pm_signals.build_board_digest(None, today)
    names = _client_names(get_supabase(), [c.get("client_id") for c in board.get("clients", [])])
    report = build_report(today, rep=rep, prev_completed=prev_completed, workload=workload,
                          board=board, names=names)
    common.attach_narrative(report, "PACE, the VP of Delivery & Operations")
    return common.emit_report(report, kind="pace_board_report", today=today, link="/workload")
