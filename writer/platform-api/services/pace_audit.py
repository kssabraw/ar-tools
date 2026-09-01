"""PACE — the action log (audit + learning ledger).

Records, best-effort, every PACE action that AFFECTS A CLIENT CAMPAIGN plus every
human decision on one (approve / approve-with-modifications / deny / defer /
cancel). Deliberately NOT every action — pure reads (delivery report, client
pulse, personal brief, drill, this module's own history tool) are excluded.

Two jobs, one stream (`public.pace_action_log`):
  1. Debuggability — "if something went wrong, why?": before/after task
     snapshot, resolved args, actor, the reason, outcome, and any error.
  2. Learning — a training-grade corpus PACE reads back via the `pace_history`
     tool (approve/deny/modify rates per action + per actor), so it can explain
     and improve its own behaviour.

Design: logging happens at PACE's OWN execution/decision seams (never at the
shared `task_service` layer), so every row is PACE-attributed and carries the
"why". Every write is best-effort — a logging failure NEVER breaks an action
(the campaign work is the priority; the record is secondary). Gated on
``settings.pace_audit_enabled`` (default True).

Pure helpers (``is_logged`` / ``task_snapshot`` / ``decision_stats`` /
``selection_modifications`` / ``format_history``) are unit-tested; the impure I/O
(``record`` / ``run_and_log`` / ``recent_actions``) is mockable.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Optional

from config import settings
from db.supabase_client import get_supabase
from services.pace_auth import ActionContext

logger = logging.getLogger(__name__)

# The PACE_ACTIONS keys that AFFECT A CLIENT CAMPAIGN — the only actions that get
# a log row. Reads (generate_pace_report, write_client_pulse) and the read-only
# tools (drill_task, pace_history) are deliberately absent.
LOGGED_ACTIONS: frozenset[str] = frozenset({
    "reassign_task", "assign_task", "set_task_due", "set_task_status",
    "unblock_task", "triage_task", "rename_task", "generate_client_month",
    "nudge_assignee", "run_qa_review",
})

# The pseudo-action for a human's decision on an intervention as a whole.
INTERVENTION_DISPOSITION = "intervention_disposition"

# Key task fields snapshotted before/after a change — enough to see exactly what
# moved without pulling the whole row or duplicating task_activity.
TASK_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "name", "assignee_name", "assignee_id", "status_key", "due_date",
    "category", "est_hours", "completed",
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def is_logged(action: Optional[str]) -> bool:
    """Whether ``action`` affects a client campaign (→ gets a log row)."""
    return action in LOGGED_ACTIONS or action == INTERVENTION_DISPOSITION


def task_snapshot(task: Optional[dict]) -> Optional[dict]:
    """Project a tasks row to the audited fields — the before/after state. None
    when there's no task (e.g. generate_client_month). Pure."""
    if not task:
        return None
    return {k: task.get(k) for k in TASK_SNAPSHOT_FIELDS}


def target_from_args(action: str, args: dict) -> dict:
    """Derive (target_type, target_id, target_name) from a staged action's args.
    Pure — task actions carry ``task_id``/``task_name``; generate_client_month
    carries ``month``; everything else is client-scoped."""
    args = args or {}
    if args.get("task_id"):
        return {"target_type": "task", "target_id": str(args["task_id"]),
                "target_name": args.get("task_name") or args.get("old_name")}
    if action == "generate_client_month" and args.get("month"):
        return {"target_type": "month", "target_id": str(args["month"]), "target_name": None}
    return {"target_type": "client", "target_id": None, "target_name": None}


def selection_modifications(n_items: int, selection: list[int]) -> Optional[dict]:
    """A Chase-Plan/batch partial approval → the {approved, dropped} modification
    record (None when everything was approved — no modification). Pure."""
    picked = sorted({i for i in (selection or []) if 1 <= i <= n_items})
    dropped = [i for i in range(1, n_items + 1) if i not in picked]
    if not dropped:
        return None
    return {"approved": picked, "dropped": dropped, "total": n_items}


def _clip(text: Any, limit: int) -> Optional[str]:
    if text is None:
        return None
    s = str(text)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def decision_stats(rows: list[dict]) -> dict:
    """Roll a set of log rows into approve/deny/modify counts overall, per action,
    and per actor — the learning substrate PACE reads back. Pure."""
    def _blank() -> dict:
        return {"approved": 0, "approved_with_modifications": 0, "denied": 0,
                "deferred": 0, "cancelled": 0, "auto": 0, "executed": 0,
                "failed": 0, "total": 0}

    overall = _blank()
    by_action: dict[str, dict] = {}
    by_actor: dict[str, dict] = {}
    for r in rows or []:
        overall["total"] += 1
        dec = r.get("decision")
        out = r.get("outcome")
        if dec in overall:
            overall[dec] += 1
        if out in overall:
            overall[out] += 1
        act = r.get("action") or "?"
        ba = by_action.setdefault(act, _blank())
        ba["total"] += 1
        if dec in ba:
            ba[dec] += 1
        if out in ba:
            ba[out] += 1
        who = r.get("actor_name") or r.get("actor_profile_id") or "system"
        bp = by_actor.setdefault(str(who), _blank())
        bp["total"] += 1
        if dec in bp:
            bp[dec] += 1
        if out in bp:
            bp[out] += 1
    return {"overall": overall, "by_action": by_action, "by_actor": by_actor}


def format_history(rows: list[dict]) -> str:
    """Compact, LLM-readable lines for the `pace_history` tool. Pure."""
    if not rows:
        return "No PACE actions on record for this scope yet."
    lines = []
    for r in rows:
        when = (r.get("created_at") or "")[:10]
        dec = r.get("decision") or r.get("outcome") or "?"
        who = r.get("actor_name") or "system"
        client = r.get("client_name") or "—"
        what = r.get("reason") or r.get("action") or "?"
        tail = ""
        if r.get("outcome") == "failed":
            tail = f" [FAILED: {_clip(r.get('error'), 80)}]"
        elif r.get("outcome") in ("cancelled", "denied", "deferred"):
            tail = f" [{r.get('outcome')}]"
        lines.append(f"- {when} · {client} · {dec} by {who}: {what}{tail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Impure I/O (best-effort — never raises into an action)
# ---------------------------------------------------------------------------
def _actor_fields(context: Optional[ActionContext]) -> dict:
    if not context:
        return {"actor_profile_id": None, "actor_role": None, "actor_source": "system"}
    return {"actor_profile_id": context.profile_id, "actor_role": context.role,
            "actor_source": context.source or "web"}


def record(*, action: str, origin: str, outcome: str,
           decision: Optional[str] = None,
           context: Optional[ActionContext] = None,
           client_id: Optional[str] = None, client_name: Optional[str] = None,
           target_type: Optional[str] = None, target_id: Optional[str] = None,
           target_name: Optional[str] = None,
           requester_profile_id: Optional[str] = None,
           reason: Optional[str] = None, args: Optional[dict] = None,
           before: Optional[dict] = None, after: Optional[dict] = None,
           modifications: Optional[dict] = None, result: Optional[str] = None,
           error: Optional[str] = None, intervention_id: Optional[str] = None,
           chase_plan_date: Optional[str] = None, extra: Optional[dict] = None) -> None:
    """Insert one ``pace_action_log`` row. Best-effort: gated on
    ``pace_audit_enabled``, and any failure is swallowed + logged (a logging
    error must never break the action that triggered it)."""
    if not settings.pace_audit_enabled:
        return
    if not is_logged(action):
        return
    af = _actor_fields(context)
    row = {
        "action": action, "origin": origin, "outcome": outcome, "decision": decision,
        "client_id": client_id, "client_name": _clip(client_name, 200),
        "target_type": target_type, "target_id": _clip(target_id, 200),
        "target_name": _clip(target_name, 300),
        "actor_profile_id": af["actor_profile_id"], "actor_role": af["actor_role"],
        "actor_source": af["actor_source"], "requester_profile_id": requester_profile_id,
        "reason": _clip(reason, 1000), "args": args or {},
        "before": before, "after": after, "modifications": modifications,
        "result": _clip(result, 1000), "error": _clip(error, 500),
        "intervention_id": intervention_id, "chase_plan_date": chase_plan_date,
        "context": extra,
    }
    try:
        get_supabase().table("pace_action_log").insert(row).execute()
    except Exception as exc:  # never surface into the action path
        logger.warning("pace_audit_record_failed",
                       extra={"action": action, "outcome": outcome, "error": str(exc)})


def _read_task(task_id: Optional[str]) -> Optional[dict]:
    """Best-effort single-task read for the before/after snapshot. None on any
    miss/error (the snapshot is a nice-to-have, never load-bearing)."""
    if not task_id:
        return None
    try:
        rows = (
            get_supabase().table("tasks")
            .select(", ".join(TASK_SNAPSHOT_FIELDS))
            .eq("id", task_id).limit(1).execute()
        ).data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("pace_audit_snapshot_failed", extra={"task_id": task_id, "error": str(exc)})
        return None


async def run_and_log(run_fn: Callable[[], Any], *, action: str, context: ActionContext,
                      client_id: Optional[str], args: Optional[dict], origin: str,
                      decision: str = "approved", reason: Optional[str] = None,
                      requester: Optional[str] = None, client_name: Optional[str] = None,
                      intervention_id: Optional[str] = None,
                      chase_plan_date: Optional[str] = None,
                      modifications: Optional[dict] = None,
                      extra: Optional[dict] = None) -> Any:
    """Run a PACE action (``run_fn`` — a bound zero-arg callable, sync or async)
    and log it. For a **logged** (campaign-affecting) action it snapshots the
    target task before/after, records outcome=executed with the result (or
    outcome=failed + the error, then re-raises), so the seams' own try/except is
    unchanged. A **non-logged** action (report/pulse) just runs — no row, no
    snapshot overhead. Returns the run's result verbatim."""
    logged = settings.pace_audit_enabled and is_logged(action)
    args = args or {}
    task_id = args.get("task_id")
    before = _read_task(task_id) if logged else None
    tgt = target_from_args(action, args)
    common = dict(action=action, origin=origin, decision=decision, context=context,
                  client_id=client_id, client_name=client_name,
                  requester_profile_id=requester, reason=reason, args=args,
                  modifications=modifications, intervention_id=intervention_id,
                  chase_plan_date=chase_plan_date, extra=extra, **tgt)
    try:
        result = run_fn()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        if logged:
            record(outcome="failed", before=task_snapshot(before), error=str(exc), **common)
        raise
    if logged:
        after = task_snapshot(_read_task(task_id)) if task_id else None
        record(outcome="executed", before=task_snapshot(before), after=after,
               result=str(result), **common)
    return result


def record_decision(*, action: str, origin: str, decision: str, outcome: str,
                    context: ActionContext, client_id: Optional[str] = None,
                    client_name: Optional[str] = None, reason: Optional[str] = None,
                    modifications: Optional[dict] = None, target_id: Optional[str] = None,
                    target_name: Optional[str] = None, target_type: Optional[str] = None,
                    intervention_id: Optional[str] = None, requester: Optional[str] = None,
                    args: Optional[dict] = None) -> None:
    """Thin wrapper for a human DECISION that isn't itself a run_and_log execution
    — a declined conversational confirm, or an intervention deny/defer/approve
    disposition. Best-effort."""
    record(action=action, origin=origin, decision=decision, outcome=outcome,
           context=context, client_id=client_id, client_name=client_name,
           reason=reason, modifications=modifications, target_id=target_id,
           target_name=target_name, target_type=target_type,
           intervention_id=intervention_id, requester_profile_id=requester, args=args or {})


# ---------------------------------------------------------------------------
# Self-read (learning) — recent history for the pace_history tool + context
# ---------------------------------------------------------------------------
def _attach_actor_names(rows: list[dict]) -> list[dict]:
    """Best-effort: fold ``actor_name`` onto each row from profiles."""
    ids = sorted({r.get("actor_profile_id") for r in rows if r.get("actor_profile_id")})
    if not ids:
        return rows
    try:
        profs = (get_supabase().table("profiles").select("id, full_name")
                 .in_("id", ids).execute()).data or []
        names = {p["id"]: p.get("full_name") for p in profs}
    except Exception:
        names = {}
    for r in rows:
        r["actor_name"] = names.get(r.get("actor_profile_id"))
    return rows


def recent_actions(*, client_id: Optional[str] = None,
                   actor_profile_id: Optional[str] = None,
                   action: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """Recent log rows for a scope, newest first, with actor names attached.
    Best-effort — returns [] on any error."""
    limit = limit or settings.pace_audit_history_limit
    try:
        q = (get_supabase().table("pace_action_log")
             .select("created_at, action, origin, decision, outcome, client_id, "
                     "client_name, target_name, actor_profile_id, reason, error, "
                     "intervention_id")
             .order("created_at", desc=True).limit(limit))
        if client_id:
            q = q.eq("client_id", client_id)
        if actor_profile_id:
            q = q.eq("actor_profile_id", actor_profile_id)
        if action:
            q = q.eq("action", action)
        rows = q.execute().data or []
    except Exception as exc:
        logger.warning("pace_audit_recent_failed", extra={"error": str(exc)})
        return []
    return _attach_actor_names(rows)


def history_summary(*, client_id: Optional[str] = None, limit: Optional[int] = None) -> dict:
    """Recent actions + a decision-rate rollup for the `pace_history` tool and the
    passive context surface. Best-effort."""
    rows = recent_actions(client_id=client_id, limit=limit)
    return {"recent": rows, "stats": decision_stats(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# Read API (admin-gated /pace/action-log)
# ---------------------------------------------------------------------------
_LOG_COLUMNS = (
    "id, created_at, action, origin, decision, outcome, client_id, client_name, "
    "target_type, target_id, target_name, actor_profile_id, actor_role, "
    "actor_source, requester_profile_id, reason, args, before, after, "
    "modifications, result, error, intervention_id, chase_plan_date"
)


def _apply_log_filters(q, *, client_id=None, actor_profile_id=None, action=None,
                       decision=None, outcome=None, origin=None, since=None, until=None):
    if client_id:
        q = q.eq("client_id", client_id)
    if actor_profile_id:
        q = q.eq("actor_profile_id", actor_profile_id)
    if action:
        q = q.eq("action", action)
    if decision:
        q = q.eq("decision", decision)
    if outcome:
        q = q.eq("outcome", outcome)
    if origin:
        q = q.eq("origin", origin)
    if since:
        q = q.gte("created_at", since)
    if until:
        q = q.lte("created_at", until)
    return q


def list_log(*, client_id=None, actor_profile_id=None, action=None, decision=None,
             outcome=None, origin=None, since=None, until=None,
             limit: int = 100, offset: int = 0) -> dict:
    """A filtered page of the action log for the admin read API, with client +
    actor names joined. Returns {rows, total, limit, offset}. Best-effort."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    try:
        q = (get_supabase().table("pace_action_log").select(_LOG_COLUMNS, count="exact")
             .order("created_at", desc=True).range(offset, offset + limit - 1))
        q = _apply_log_filters(q, client_id=client_id, actor_profile_id=actor_profile_id,
                               action=action, decision=decision, outcome=outcome,
                               origin=origin, since=since, until=until)
        resp = q.execute()
        rows = resp.data or []
        total = resp.count if resp.count is not None else len(rows)
    except Exception as exc:
        logger.warning("pace_audit_list_failed", extra={"error": str(exc)})
        return {"rows": [], "total": 0, "limit": limit, "offset": offset}
    return {"rows": _attach_actor_names(rows), "total": total, "limit": limit, "offset": offset}


def stats_window(*, client_id=None, actor_profile_id=None, action=None,
                 since=None, until=None, limit: int = 1000) -> dict:
    """Decision-rate rollup over a filtered window (a wider read than the
    self-history default) for the log view's summary strip. Best-effort."""
    cap = min(int(limit or 1000), 5000)
    try:
        q = (get_supabase().table("pace_action_log")
             .select("action, decision, outcome, actor_profile_id")
             .order("created_at", desc=True).limit(cap))
        q = _apply_log_filters(q, client_id=client_id, actor_profile_id=actor_profile_id,
                               action=action, since=since, until=until)
        rows = _attach_actor_names(q.execute().data or [])
    except Exception as exc:
        logger.warning("pace_audit_stats_failed", extra={"error": str(exc)})
        rows = []
    return decision_stats(rows)
