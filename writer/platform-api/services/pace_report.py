"""PACE v1.3 Phase 6 — delivery (PM status) reports (§4.7).

The internal PM status report — throughput, overdue & stuck, capacity
utilization, backlog health, and behind-pace clients — for a single client or
portfolio-wide. Distinct from the client-facing Client Reporting module (that
one is external + owner-friendly); this is for leads/owners.

Deterministic core over `pm_signals` + `task_workload` + the `tasks` table (no
LLM, no paid calls). Pure aggregations are unit-tested; the impure `build_report`
gathers live state. Delivery: the `generate_pace_report` PACE action (assistant
chat/Slack), the `GET .../pace-report` API (the Workload Reports card), and an
optional weekly digest on the shared scheduler (`pace_report_weekday`, off by
default).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, pm_signals, task_workload

logger = logging.getLogger(__name__)

DEFAULT_PERIOD_DAYS = 7

# The Asana importer completes historical tasks via complete_task(), which
# stamps completed_at = IMPORT time — so a fresh import dumps months of old
# completions into "this week". An import-stamped completion is created and
# completed in nearly the same instant; a task imported OPEN and finished
# natively later has completed_at ≫ created_at, so it still counts.
_IMPORT_STAMP_WINDOW_SECONDS = 600


def _ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_import_stamped(row: dict) -> bool:
    """True when a completed task's completed_at is an import artifact (source
    'asana_import' + completed within minutes of its own creation). Pure."""
    if row.get("source") != "asana_import":
        return False
    created, completed = _ts(row.get("created_at")), _ts(row.get("completed_at"))
    if not created or not completed:
        return True  # unparseable import row — safer to exclude than inflate
    return (completed - created).total_seconds() < _IMPORT_STAMP_WINDOW_SECONDS


# ---------------------------------------------------------------------------
# Pure aggregations (unit-tested)
# ---------------------------------------------------------------------------
def throughput(completed_rows: list[dict], *, by: str) -> dict:
    """Count completed tasks grouped by ``category`` or ``assignee_name``.
    Pure. Empty/None keys fold into 'Uncategorized' / 'Unassigned'."""
    fallback = "Uncategorized" if by == "category" else "Unassigned"
    out: dict = {}
    for r in completed_rows:
        key = (r.get(by) or "").strip() or fallback
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def utilization(workload_members: list[dict]) -> list[dict]:
    """Per-member committed hours vs weekly capacity. Pure.
    Returns [{name, committed, capacity, pct, over}] sorted most-loaded first."""
    rows = []
    for m in workload_members:
        cap = m.get("weekly_hours") or 0
        committed = m.get("open_hours") or 0
        pct = round(100 * committed / cap) if cap else None
        rows.append({
            "name": m.get("name") or m.get("gid"),
            "committed": committed, "capacity": cap,
            "pct": pct, "over": bool(m.get("overloaded")),
        })
    return sorted(rows, key=lambda r: (-(r["pct"] if r["pct"] is not None else -1), r["name"] or ""))


def summarize(clients: list[dict]) -> dict:
    """Roll the per-client PACE envelopes into portfolio counts. Pure."""
    return {
        "stuck": sum(len(c.get("stale", [])) for c in clients),
        "overdue": sum(len(c.get("overdue", [])) for c in clients),
        "unassigned": sum(len(c.get("unassigned", [])) for c in clients),
        "unacted": sum(len(c.get("unacted_producer", [])) for c in clients),
        "behind_pace": sum(1 for c in clients if (c.get("month_pace") or {}).get("behind")),
    }


# ---------------------------------------------------------------------------
# Impure gather
# ---------------------------------------------------------------------------
def _completed_since(client_id: Optional[str], since: date) -> list[dict]:
    q = (
        get_supabase().table("tasks")
        .select("category, assignee_name, completed_at, created_at, source")
        .eq("completed", True).is_("deleted_at", "null").is_("parent_task_id", "null")
        .gte("completed_at", since.isoformat())
    )
    if client_id:
        q = q.eq("client_id", client_id)
    rows = q.execute().data or []
    return [r for r in rows if not is_import_stamped(r)]


def build_report(client_id: Optional[str] = None, *, today: Optional[date] = None,
                 period_days: int = DEFAULT_PERIOD_DAYS) -> dict:
    """The deterministic delivery report — one client or portfolio."""
    today = today or date.today()
    since = today - timedelta(days=period_days)
    digest = pm_signals.build_board_digest(client_id)
    clients = digest.get("clients", [])
    completed = _completed_since(client_id, since)
    members = task_workload.build_team_workload().get("members", [])
    return {
        "scope": "client" if client_id else "portfolio",
        "as_of": today.isoformat(),
        "period_days": period_days,
        "clients_covered": len(clients),
        "completed_count": len(completed),
        "throughput_by_category": throughput(completed, by="category"),
        "throughput_by_person": throughput(completed, by="assignee_name"),
        **summarize(clients),
        "utilization": utilization(members),
    }


# ---------------------------------------------------------------------------
# Render (pure, Slack/Markdown)
# ---------------------------------------------------------------------------
def _kv_lines(d: dict, limit: int = 6) -> str:
    items = list(d.items())[:limit]
    return "; ".join(f"{k}: {v}" for k, v in items) if items else "—"


def render_text(report: dict, *, scope_name: Optional[str] = None) -> str:
    """A concise Markdown delivery report for the assistant chat / Slack. Pure."""
    scope = scope_name or ("this client" if report.get("scope") == "client" else "all clients")
    days = report.get("period_days", DEFAULT_PERIOD_DAYS)
    lines = [f"*Delivery report — {scope}* (last {days}d, as of {report.get('as_of')})"]
    lines.append(
        f"• Completed: *{report.get('completed_count', 0)}* tasks"
        + (f" across {report.get('clients_covered', 0)} clients" if report.get("scope") == "portfolio" else "")
    )
    lines.append(
        f"• Open issues: {report.get('overdue', 0)} overdue · {report.get('stuck', 0)} stuck · "
        f"{report.get('unassigned', 0)} unassigned · {report.get('unacted', 0)} unacted · "
        f"{report.get('behind_pace', 0)} behind pace"
    )
    if report.get("throughput_by_person"):
        lines.append(f"• By person: {_kv_lines(report['throughput_by_person'])}")
    if report.get("throughput_by_category"):
        lines.append(f"• By type: {_kv_lines(report['throughput_by_category'])}")
    util = report.get("utilization") or []
    over = [u for u in util if u.get("over")]
    if over:
        lines.append("• Over capacity: " + ", ".join(
            f"{u['name']} ({u['pct']}%)" if u.get("pct") is not None else u["name"] for u in over
        ))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Weekly auto-digest (shared scheduler, off by default)
# ---------------------------------------------------------------------------
def maybe_emit_weekly(today: Optional[date] = None) -> dict:
    """Emit ONE portfolio delivery report per week on `pace_report_weekday`.
    Self-gated on `pace_enabled` + a configured weekday; best-effort. Called
    inline from the daily scheduler tick."""
    if not settings.pace_enabled:
        return {"emitted": False, "reason": "disabled"}
    weekday = settings.pace_report_weekday
    today = today or date.today()
    if weekday is None or today.weekday() != int(weekday):
        return {"emitted": False, "reason": "not_due"}
    try:
        report = build_report(None, today=today)
        notifications.emit(
            client_id=None, kind="pace_report",
            title=f"Weekly delivery report — {report['completed_count']} completed, "
                  f"{report.get('overdue', 0)} overdue",
            summary=render_text(report, scope_name="all clients"),
            severity="info",
            payload={"link": "/workload", "slack_channel": settings.pace_slack_channel or None},
            dedupe_key=f"pace_report:{today.isoformat()}:portfolio",
        )
        return {"emitted": True}
    except Exception as exc:
        logger.warning("pace_report.weekly_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error"}
