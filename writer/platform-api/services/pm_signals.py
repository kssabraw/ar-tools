"""PACE — deterministic signal layer (Phase 0A).

docs/modules/project-manager-agent-plan-v1_0.md §2b. Pure, unit-tested rules
over the native task tables — **no LLM, no paid calls, no writes**. The PACE
persona (later phases) only prioritizes / phrases / acts on what these builders
surface; this layer decides *what counts as a delivery problem* deterministically.

Design rules honored here:
- **Configurable-workflow-safe:** status logic keys off the status's coarse
  ``category`` (`not_started|in_progress|blocked|done`) + `is_initial`/`is_done`,
  with an optional per-status-key threshold override — never hardcoded keys.
- **Reopen-aware staleness:** the status clock resets on ``created`` /
  ``status_changed`` / ``reopened`` (``reopen_task`` emits ``reopened``, not
  ``status_changed``), so a long-idle task reopened today reads *fresh*.
- **Month-pace is a heuristic**, dual-mode (calendar proxy → due-date-weighted
  once enough due dates exist), with early-month + small-board suppression.
- **Unacted-on** (not "unopened"): viewing writes no activity, so the producer
  signal claims only "nobody assigned / changed / commented".

The pure helpers take primitives so they're trivially unit-tested; the single
impure assembler (`build_client_signals` / `build_board_digest`) does the I/O.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import task_service, task_workload

# Producer sources whose auto-created tasks we watch for "unacted-on" (PRD §11).
_PRODUCER_SOURCES = {"rank_drop", "maps_alert", "action_plan", "content_run"}
# Activity kinds that reset the status clock (see module docstring).
_CLOCK_RESET_KINDS = {"created", "status_changed", "reopened"}


# ---------------------------------------------------------------------------
# Date helpers (pure)
# ---------------------------------------------------------------------------
def to_date(value) -> Optional[date]:
    """Coerce a date / datetime / ISO string (date or timestamptz) to a ``date``
    at day granularity. Returns None on anything unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def business_days_in_month(year: int, month: int) -> int:
    """Count of Mon–Fri days in a month. (No holiday calendar in v1.)"""
    d = date(year, month, 1)
    n = 0
    while d.month == month:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def business_days_elapsed(today: date) -> int:
    """Mon–Fri days from the 1st of ``today``'s month through ``today`` inclusive."""
    d = today.replace(day=1)
    n = 0
    while d <= today:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
# Staleness (pure)
# ---------------------------------------------------------------------------
def status_clock_start(task: dict, activities: list[dict]) -> Optional[date]:
    """The date the task's current status clock started: the most recent
    clock-reset activity (created/status_changed/reopened), falling back to the
    task's creation date when no activity is available."""
    resets = [
        to_date(a.get("created_at"))
        for a in activities
        if a.get("kind") in _CLOCK_RESET_KINDS and a.get("created_at")
    ]
    resets = [d for d in resets if d]
    return max(resets) if resets else to_date(task.get("created_at"))


def days_in_status(task: dict, activities: list[dict], today: date) -> Optional[int]:
    start = status_clock_start(task, activities)
    return (today - start).days if start else None


def stale_threshold(
    status_key: Optional[str],
    status_category: Optional[str],
    thresholds: dict,
    category_fallback: dict,
) -> Optional[int]:
    """Days-in-status threshold for a status: its per-key override if any, else
    the coarse-category fallback, else None (→ never stale on a timer)."""
    if status_key and status_key in thresholds:
        return thresholds[status_key]
    if status_category and status_category in category_fallback:
        return category_fallback[status_category]
    return None


def is_stale(days: Optional[int], threshold: Optional[int]) -> bool:
    return threshold is not None and days is not None and days >= threshold


# ---------------------------------------------------------------------------
# Month-pace heuristic (pure, dual-mode)
# ---------------------------------------------------------------------------
def month_pace(tasks: list[dict], today: date, *, grace: float, min_tasks: int,
               suppress_business_days: int) -> dict:
    """Per-client month-pace *hint* over top-level tasks. Suppressed in the first
    ``suppress_business_days`` of the month and on boards under ``min_tasks``.
    Once ≥ half the tasks carry due dates, uses due-date-weighted expected
    progress; otherwise a business-day calendar proxy. Returns a dict with
    ``applicable`` + (when applicable) ``mode``/``behind`` and the ratios."""
    top = [t for t in tasks if not t.get("parent_task_id")]
    total = len(top)
    if total < min_tasks:
        return {"applicable": False, "reason": "too_few_tasks", "total": total}
    if business_days_elapsed(today) <= suppress_business_days:
        return {"applicable": False, "reason": "early_month", "total": total}

    dated = [t for t in top if t.get("due_date")]
    if dated and len(dated) * 2 >= total:
        denom = len(dated)
        expected = sum(1 for t in dated if (to_date(t["due_date"]) or today) <= today) / denom
        actual = sum(1 for t in dated if t.get("completed")) / denom
        return {
            "applicable": True, "mode": "due_weighted", "total": total,
            "expected": round(expected, 3), "actual": round(actual, 3),
            "behind": actual + grace < expected,
        }

    pct_complete = sum(1 for t in top if t.get("completed")) / total
    biz_total = business_days_in_month(today.year, today.month)
    pct_elapsed = (business_days_elapsed(today) / biz_total) if biz_total else 0.0
    return {
        "applicable": True, "mode": "calendar", "total": total,
        "pct_complete": round(pct_complete, 3), "pct_elapsed": round(pct_elapsed, 3),
        "behind": pct_complete + grace < pct_elapsed,
    }


# ---------------------------------------------------------------------------
# Triage signals (pure)
# ---------------------------------------------------------------------------
def is_unacted_producer_task(task: dict, activities: list[dict]) -> bool:
    """A producer-created, still-open task whose only activity is ``created`` —
    nobody has assigned, changed, or commented on it. "Unacted-on", not
    "unopened" (viewing writes no activity)."""
    if task.get("source") not in _PRODUCER_SOURCES or task.get("completed"):
        return False
    kinds = {a.get("kind") for a in activities}
    return kinds <= {"created"}


def select_untriaged(tasks: list[dict], today: date, grace_days: int) -> dict:
    """Open top-level tasks past a creation-grace window that are unassigned or
    have no due date. Grace keeps brand-new work from nagging immediately."""
    cutoff = today - timedelta(days=grace_days)
    unassigned, no_due = [], []
    for t in tasks:
        if t.get("completed") or t.get("parent_task_id"):
            continue
        created = to_date(t.get("created_at"))
        if created and created > cutoff:
            continue  # too fresh to nag
        if not t.get("assignee_gid"):
            unassigned.append(t)
        if not t.get("due_date"):
            no_due.append(t)
    return {"unassigned": unassigned, "no_due": no_due}


# ---------------------------------------------------------------------------
# Impure assembler — the standard PACE envelope
# ---------------------------------------------------------------------------
def _open_top_level(client_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("tasks")
        .select("id, client_id, section_id, name, assignee_gid, assignee_name, "
                "status_key, category, due_date, completed, source, source_ref, created_at")
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
        .is_("parent_task_id", "null")
        .execute()
    ).data or []


def _activity_by_task(task_ids: list[str]) -> dict[str, list[dict]]:
    if not task_ids:
        return {}
    rows = (
        get_supabase()
        .table("task_activity")
        .select("task_id, kind, created_at")
        .in_("task_id", task_ids)
        .execute()
    ).data or []
    by_task: dict[str, list[dict]] = {}
    for r in rows:
        by_task.setdefault(r["task_id"], []).append(r)
    return by_task


def build_client_signals(client_id: str, today: Optional[date] = None,
                         statuses: Optional[list[dict]] = None) -> dict:
    """The deterministic PACE envelope for one client — stale tasks, overdue,
    unassigned/dateless, unacted-on producer tasks, and month pace. Pure math
    over one board's reads; no LLM, no writes."""
    today = today or date.today()
    statuses = statuses if statuses is not None else task_service.get_statuses(active_only=False)
    cat_by_key = {s["key"]: s.get("category") for s in statuses}

    tasks = _open_top_level(client_id)
    open_tasks = [t for t in tasks if not t.get("completed")]
    acts = _activity_by_task([t["id"] for t in tasks])

    stale = []
    for t in open_tasks:
        a = acts.get(t["id"], [])
        days = days_in_status(t, a, today)
        thr = stale_threshold(
            t.get("status_key"), cat_by_key.get(t.get("status_key")),
            settings.pace_stale_thresholds, settings.pace_stale_category_fallback,
        )
        if is_stale(days, thr):
            stale.append({"id": t["id"], "name": t.get("name"), "assignee_name": t.get("assignee_name"),
                          "status_key": t.get("status_key"), "category": cat_by_key.get(t.get("status_key")),
                          "days": days, "threshold": thr})
    stale.sort(key=lambda s: s["days"], reverse=True)

    overdue = [
        {"id": t["id"], "name": t.get("name"), "assignee_name": t.get("assignee_name"), "due_date": t.get("due_date")}
        for t in open_tasks
        if t.get("due_date") and (to_date(t["due_date"]) or today) < today
    ]
    overdue.sort(key=lambda o: o.get("due_date") or "")

    unacted = [
        {"id": t["id"], "name": t.get("name"), "source": t.get("source")}
        for t in open_tasks
        if is_unacted_producer_task(t, acts.get(t["id"], []))
    ]
    triage = select_untriaged(tasks, today, settings.pace_untriaged_grace_days)
    pace = month_pace(
        tasks, today,
        grace=settings.pace_month_pace_grace,
        min_tasks=settings.pace_month_pace_min_tasks,
        suppress_business_days=settings.pace_month_pace_suppress_business_days,
    )

    return {
        "client_id": client_id,
        "open_count": len(open_tasks),
        "stale": stale,
        "overdue": overdue,
        "unassigned": [{"id": t["id"], "name": t.get("name")} for t in triage["unassigned"]],
        "no_due_date": [{"id": t["id"], "name": t.get("name")} for t in triage["no_due"]],
        "unacted_producer": unacted,
        "month_pace": pace,
        # Convenience counts for the (later) digest ranking.
        "counts": {
            "stale": len(stale), "overdue": len(overdue),
            "unassigned": len(triage["unassigned"]), "unacted_producer": len(unacted),
            "behind_pace": 1 if pace.get("behind") else 0,
        },
    }


def build_board_digest(client_id: Optional[str] = None, today: Optional[date] = None) -> dict:
    """The full PACE read: one client (``client_id`` set) or **portfolio** (None
    → every client with open top-level tasks), plus the shared workload report.
    Deterministic; the digest/persona layers consume this."""
    today = today or date.today()
    statuses = task_service.get_statuses(active_only=False)

    if client_id:
        client_ids = [client_id]
    else:
        rows = (
            get_supabase()
            .table("tasks")
            .select("client_id")
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
            .not_.is_("client_id", "null")
            .execute()
        ).data or []
        client_ids = sorted({r["client_id"] for r in rows if r.get("client_id")})

    clients = [build_client_signals(cid, today, statuses) for cid in client_ids]
    # Workload is agency-wide; reuse the tested engine verbatim.
    workload = task_workload.build_team_workload()
    return {"as_of": today.isoformat(), "clients": clients, "workload": workload}
