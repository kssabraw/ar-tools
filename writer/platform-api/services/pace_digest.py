"""PACE — the daily informational digest (Phase 0B).

docs/modules/project-manager-agent-plan-v1_0.md §4.3/§6/§8. A once-per-workday,
**agency-level**, client-grouped, capped digest built **deterministically** (no
LLM — Phase 3 adds an LLM ranking on top) from the `pm_signals` layer, delivered
via the shared `notifications.emit`.

Design rules honored:
- **Informational (Option A):** `notifications.emit` posts a standalone channel
  message and can't stage a `_pending` action, so the digest names problems +
  the exact command to run; actions are invoked explicitly in the assistant.
- **Atomic dedupe:** emitted with a unique `dedupe_key` = ``pace_digest:<date>:
  portfolio`` so a rolling-deploy re-run is a DB-level no-op (the in-memory
  scheduler guard resets on deploy; the query-guard had a TOCTOU race).
- **Silent when all-clear:** nothing actionable → no message.
- **Self-gated:** does nothing unless `pace_enabled` (default False), and only
  on workdays when `pace_digest_weekday_only`.

Pure ranking/formatting helpers are unit-tested; the runner does the I/O + emit.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, pm_signals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure ranking + formatting (unit-tested)
# ---------------------------------------------------------------------------
def dedupe_key(today: date) -> str:
    return f"pace_digest:{today.isoformat()}:portfolio"


def rank_digest_items(clients: list[dict], max_items: int) -> tuple[list[dict], int]:
    """Flatten each client's signals into ranked digest candidates and cap them.
    Higher priority = more urgent: blocked-stale > other-stale > overdue >
    unacted producer > behind pace > unassigned. Returns (top_items, total).
    Pure — unit-tested."""
    items: list[dict] = []
    for c in clients:
        cid = c.get("client_id")
        for s in c.get("stale", []):
            base = 100 if s.get("category") == "blocked" else 70
            items.append({
                "client_id": cid, "category": "stale", "priority": base + (s.get("days") or 0),
                "task_name": s.get("name"), "status_key": s.get("status_key"),
                "days": s.get("days"), "assignee_name": s.get("assignee_name"),
            })
        for u in c.get("unacted_producer", []):
            items.append({
                "client_id": cid, "category": "unacted_producer", "priority": 50,
                "task_name": u.get("name"), "source": u.get("source"),
            })
        overdue = c.get("overdue", [])
        if overdue:
            items.append({"client_id": cid, "category": "overdue",
                          "priority": 60 + len(overdue), "count": len(overdue)})
        if (c.get("month_pace") or {}).get("behind"):
            items.append({"client_id": cid, "category": "behind_pace", "priority": 40})
        unassigned = c.get("unassigned", [])
        if unassigned:
            items.append({"client_id": cid, "category": "unassigned",
                          "priority": 20, "count": len(unassigned)})
    # Stable sort: priority desc, then client_id so a client's items group.
    items.sort(key=lambda i: (-i["priority"], str(i.get("client_id"))))
    return items[:max_items], len(items)


def _line(item: dict, names: dict) -> str:
    name = names.get(item.get("client_id"), "Client")
    cat = item["category"]
    if cat == "stale":
        who = f" ({item['assignee_name']})" if item.get("assignee_name") else ""
        return f"*{name}* — “{item['task_name']}” {item.get('status_key')} {item['days']}d{who} → `@PACE unblock {item['task_name']} on {name}`"
    if cat == "unacted_producer":
        return f"*{name}* — “{item['task_name']}” ({item['source']}) unacted → `@PACE assign it`"
    if cat == "overdue":
        return f"*{name}* — {item['count']} task{'s' if item['count'] != 1 else ''} overdue"
    if cat == "behind_pace":
        return f"*{name}* — behind pace (heuristic)"
    if cat == "unassigned":
        return f"*{name}* — {item['count']} unassigned"
    return f"*{name}* — {cat}"


def format_digest(items: list[dict], total: int, client_names: dict) -> str:
    """The digest body (mrkdwn). Pure — unit-tested."""
    lines = [f"• {_line(i, client_names)}" for i in items]
    if total > len(items):
        lines.append(f"… +{total - len(items)} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner (I/O + emit) — inline on the shared scheduler
# ---------------------------------------------------------------------------
def _client_names(client_ids: list[str]) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (
        get_supabase().table("clients").select("id, name").in_("id", ids).execute()
    ).data or []
    return {r["id"]: r.get("name") for r in rows}


def run_daily_digest(today: Optional[date] = None) -> dict:
    """Build + emit the daily PACE digest (portfolio). Self-gated + best-effort;
    returns a summary dict. No-ops silently when nothing is actionable."""
    today = today or date.today()
    if not settings.pace_enabled:
        return {"emitted": False, "reason": "disabled"}
    if settings.pace_digest_weekday_only and today.weekday() >= 5:
        return {"emitted": False, "reason": "weekend"}
    try:
        board = pm_signals.build_board_digest(None, today)
        items, total = rank_digest_items(board.get("clients", []), settings.pace_digest_max_items)
        if not items:
            return {"emitted": False, "reason": "all_clear"}
        names = _client_names([i.get("client_id") for i in items])
        body = format_digest(items, total, names)
        key = dedupe_key(today)
        nid = notifications.emit(
            client_id=None,
            kind="pace_digest",
            title=f"PACE daily · {total} item{'s' if total != 1 else ''} need a human",
            summary=body,
            severity="info",
            payload={"link": "/tasks", "digest_key": key,
                     "slack_channel": settings.pace_slack_channel or None},
            dedupe_key=key,
        )
        return {"emitted": nid is not None, "items": len(items), "total": total,
                "deduped": nid is None}
    except Exception as exc:  # never break the scheduler tick
        logger.warning("pace_digest_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error", "error": str(exc)[:200]}
