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
    """Roll a set of log rows into approve/deny/modify/revert counts overall, per
    action, and per actor — the learning substrate PACE reads back. Pure. A
    ``reverted`` count comes from ``reverted_at`` being set on a row (an executed
    action later undone), so it can co-occur with executed."""
    def _blank() -> dict:
        return {"approved": 0, "approved_with_modifications": 0, "denied": 0,
                "deferred": 0, "cancelled": 0, "auto": 0, "executed": 0,
                "failed": 0, "reverted": 0, "total": 0}

    def _tally(bucket: dict, dec, out, reverted) -> None:
        bucket["total"] += 1
        if dec in bucket:
            bucket[dec] += 1
        if out in bucket:
            bucket[out] += 1
        if reverted:
            bucket["reverted"] += 1

    overall = _blank()
    by_action: dict[str, dict] = {}
    by_actor: dict[str, dict] = {}
    for r in rows or []:
        dec, out, rev = r.get("decision"), r.get("outcome"), bool(r.get("reverted_at"))
        _tally(overall, dec, out, rev)
        _tally(by_action.setdefault(r.get("action") or "?", _blank()), dec, out, rev)
        who = r.get("actor_name") or r.get("actor_profile_id") or "system"
        _tally(by_actor.setdefault(str(who), _blank()), dec, out, rev)
    return {"overall": overall, "by_action": by_action, "by_actor": by_actor}


# ---------------------------------------------------------------------------
# Revert detection (pure) — did a human undo what PACE did?
# ---------------------------------------------------------------------------
def changed_fields(before: Optional[dict], after: Optional[dict]) -> list[str]:
    """The snapshot fields PACE actually changed (before != after). Pure."""
    if not before or not after:
        return []
    return [k for k in after if k in before and before.get(k) != after.get(k)]


def classify_revert(before: Optional[dict], after: Optional[dict],
                    current: Optional[dict]) -> Optional[dict]:
    """Compare a task's CURRENT state to what PACE set. For the first field PACE
    changed that has since moved off PACE's value: ``reverted`` when it's back at
    the pre-PACE value, else ``overridden``. None when PACE's change still stands
    (or the task is gone). Pure — reverted wins over overridden when both exist."""
    if not current:
        return None
    fields = changed_fields(before, after)
    overridden = None
    for f in fields:
        pace_val, cur = (after or {}).get(f), current.get(f)
        if cur == pace_val:
            continue  # PACE's change still stands for this field
        kind = "reverted" if cur == (before or {}).get(f) else "overridden"
        detail = {"field": f, "from_pace": pace_val, "to_current": cur, "kind": kind}
        if kind == "reverted":
            return detail  # strongest signal — return immediately
        overridden = overridden or detail
    return overridden


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
        if r.get("reverted_at"):
            tail += " [REVERTED — a human undid this]"
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
    ids = sorted({str(r["actor_profile_id"]) for r in rows if r.get("actor_profile_id")})
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
                   action: Optional[str] = None, limit: Optional[int] = None,
                   attach_names: bool = True) -> list[dict]:
    """Recent log rows for a scope, newest first. Includes revert state so the
    self-read reflects undone actions (parity with the digest). ``attach_names``
    False skips the extra profiles join — used by the passive context summary,
    which needs only counts, not actor names. Best-effort — [] on any error."""
    limit = limit or settings.pace_audit_history_limit
    try:
        q = (get_supabase().table("pace_action_log")
             .select("created_at, action, origin, decision, outcome, client_id, "
                     "client_name, target_name, actor_profile_id, reason, error, "
                     "intervention_id, reverted_at, revert_detail")
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
    return _attach_actor_names(rows) if attach_names else rows


def history_summary(*, client_id: Optional[str] = None, limit: Optional[int] = None,
                    attach_names: bool = True) -> dict:
    """Recent actions + a decision-rate rollup for the `pace_history` tool and the
    passive context surface. ``attach_names`` False (the passive counts-only
    surface) skips the profiles join. Best-effort."""
    rows = recent_actions(client_id=client_id, limit=limit, attach_names=attach_names)
    return {"recent": rows, "stats": decision_stats(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# Read API (admin-gated /pace/action-log)
# ---------------------------------------------------------------------------
_LOG_COLUMNS = (
    "id, created_at, action, origin, decision, outcome, client_id, client_name, "
    "target_type, target_id, target_name, actor_profile_id, actor_role, "
    "actor_source, requester_profile_id, reason, args, before, after, "
    "modifications, result, error, intervention_id, chase_plan_date, "
    "reverted_at, revert_detail"
)


def _apply_log_filters(q, *, client_id=None, actor_profile_id=None, action=None,
                       decision=None, outcome=None, origin=None, since=None, until=None,
                       reverted=None):
    if reverted is True:
        q = q.not_.is_("reverted_at", "null")
    elif reverted is False:
        q = q.is_("reverted_at", "null")
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
             outcome=None, origin=None, since=None, until=None, reverted=None,
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
                               origin=origin, since=since, until=until, reverted=reverted)
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
             .select("action, decision, outcome, actor_profile_id, reverted_at")
             .order("created_at", desc=True).limit(cap))
        q = _apply_log_filters(q, client_id=client_id, actor_profile_id=actor_profile_id,
                               action=action, since=since, until=until)
        rows = _attach_actor_names(q.execute().data or [])
    except Exception as exc:
        logger.warning("pace_audit_stats_failed", extra={"error": str(exc)})
        rows = []
    return decision_stats(rows)


# ---------------------------------------------------------------------------
# Revert sweep (impure, daily, read-only w.r.t. tasks)
# ---------------------------------------------------------------------------
def run_revert_sweep(today: Optional[Any] = None) -> dict:
    """Mark executed, task-targeted actions whose change was undone/overridden
    since PACE made it. Read-only w.r.t. tasks — reads their current state and
    writes only pace_action_log. Self-gated on pace_audit_enabled; best-effort.
    Returns {checked, reverted}."""
    from datetime import datetime, timedelta, timezone

    if not settings.pace_audit_enabled:
        return {"checked": 0, "reverted": 0, "reason": "disabled"}
    since = (datetime.now(timezone.utc)
             - timedelta(days=settings.pace_audit_revert_window_days)).isoformat()
    try:
        rows = (get_supabase().table("pace_action_log")
                .select("id, target_id, before, after")
                .eq("outcome", "executed").eq("target_type", "task")
                .is_("reverted_at", "null").gte("created_at", since)
                .not_.is_("after", "null").limit(2000).execute()).data or []
    except Exception as exc:
        logger.warning("pace_audit_revert_query_failed", extra={"error": str(exc)})
        return {"checked": 0, "reverted": 0, "reason": "error"}
    task_ids = sorted({r["target_id"] for r in rows if r.get("target_id")})
    if not task_ids:
        return {"checked": 0, "reverted": 0}
    current: dict[str, dict] = {}
    try:
        # Chunk the id list so a big backlog stays under URL/row limits.
        for i in range(0, len(task_ids), 200):
            chunk = task_ids[i:i + 200]
            got = (get_supabase().table("tasks")
                   .select("id, " + ", ".join(TASK_SNAPSHOT_FIELDS))
                   .in_("id", chunk).is_("deleted_at", "null").execute()).data or []
            for t in got:
                current[t["id"]] = t
    except Exception as exc:
        logger.warning("pace_audit_revert_read_failed", extra={"error": str(exc)})
        return {"checked": 0, "reverted": 0, "reason": "error"}
    reverted = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        cur = current.get(r.get("target_id"))
        if cur is None:  # task gone/deleted — leave the row unmarked
            continue
        detail = classify_revert(r.get("before"), r.get("after"), cur)
        # Record TRUE reverts only (a field back to its exact pre-PACE value).
        # An "overridden" field (changed to a THIRD value) is deliberately NOT
        # marked: normal forward workflow progression (in_qa → sent_to_client) is
        # exactly that shape, so counting it would swamp the learning signal with
        # successful progress. Overrides are left unmarked (re-checked next sweep
        # until they age out of the window, or become a true revert).
        if not detail or detail.get("kind") != "reverted":
            continue
        try:
            (get_supabase().table("pace_action_log")
             .update({"reverted_at": now, "revert_detail": detail})
             .eq("id", r["id"]).execute())
        except Exception as exc:
            logger.warning("pace_audit_revert_mark_failed", extra={"id": r["id"], "error": str(exc)})
            continue
        reverted += 1
    return {"checked": len(rows), "reverted": reverted}


# ---------------------------------------------------------------------------
# Learning read model (pure) — the substrate for the digest + auto-adjust
# ---------------------------------------------------------------------------
def learning_signals(rows: list[dict]) -> dict:
    """Per-action and per-(client, action) approve/deny/modify/revert counts +
    a reject_rate = (denied + reverted) / total. The shared substrate for the
    weekly digest and the proposal penalty. Pure."""
    def _blank() -> dict:
        return {"approved": 0, "denied": 0, "modified": 0, "reverted": 0,
                "executed": 0, "total": 0}

    def _tally(b: dict, r: dict) -> None:
        b["total"] += 1
        dec = r.get("decision")
        if dec == "approved":
            b["approved"] += 1
        elif dec == "approved_with_modifications":
            b["approved"] += 1
            b["modified"] += 1
        elif dec in ("denied", "cancelled"):
            b["denied"] += 1
        if r.get("outcome") == "executed":
            b["executed"] += 1
        if r.get("reverted_at"):
            b["reverted"] += 1

    def _rate(b: dict) -> dict:
        b["reject_rate"] = round((b["denied"] + b["reverted"]) / b["total"], 3) if b["total"] else 0.0
        return b

    by_action: dict[str, dict] = {}
    by_client_action: dict[str, dict] = {}
    for r in rows or []:
        act = r.get("action") or "?"
        _tally(by_action.setdefault(act, _blank()), r)
        key = f"{r.get('client_id') or '-'}::{act}"
        _tally(by_client_action.setdefault(key, _blank()), r)
    for b in by_action.values():
        _rate(b)
    for b in by_client_action.values():
        _rate(b)
    return {"by_action": by_action, "by_client_action": by_client_action}


def _penalty_from(sig: dict) -> tuple[float, Optional[str]]:
    """(factor, note) for a signal bucket — factor scales a proposal's priority
    down as reject_rate rises above the threshold, gated by min samples. Pure."""
    total = sig.get("total", 0)
    if total < settings.pace_audit_learning_min_samples:
        return 1.0, None
    rr = sig.get("reject_rate", 0.0)
    if rr < settings.pace_audit_learning_reject_threshold:
        return 1.0, None
    # Linear demotion from 1.0 at the threshold down to 0.2 at reject_rate 1.0.
    thr = settings.pace_audit_learning_reject_threshold
    factor = max(0.2, 1.0 - (rr - thr) / max(1e-6, 1.0 - thr) * 0.8)
    declined = sig["denied"] + sig["reverted"]
    note = f"you've declined/undone this {declined} of {total} recent times"
    return round(factor, 3), note


def proposal_penalty(action: str, client_id: Optional[str],
                     signals: Optional[dict] = None) -> tuple[float, Optional[str]]:
    """Priority factor + note for a Chase-Plan proposal, from the learning
    signals (per-(client, action), falling back to agency-wide per-action). When
    learning is disabled or there's not enough history, returns (1.0, None) — so
    the Chase Plan is byte-identical to today. Best-effort."""
    if not settings.pace_audit_learning_enabled:
        return 1.0, None
    try:
        sig = signals if signals is not None else _learning_signals_window()
        ca = sig.get("by_client_action", {}).get(f"{client_id or '-'}::{action}")
        if ca and ca.get("total", 0) >= settings.pace_audit_learning_min_samples:
            return _penalty_from(ca)
        return _penalty_from(sig.get("by_action", {}).get(action, {}))
    except Exception as exc:
        logger.warning("pace_audit_penalty_failed", extra={"action": action, "error": str(exc)})
        return 1.0, None


def _learning_signals_window() -> dict:
    """Learning signals over the configured window — one read, reused across a
    plan build. Best-effort ([] on error → empty signals)."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc)
             - timedelta(days=settings.pace_audit_learning_window_days)).isoformat()
    try:
        rows = (get_supabase().table("pace_action_log")
                .select("action, client_id, decision, outcome, reverted_at")
                .gte("created_at", since).limit(5000).execute()).data or []
    except Exception:
        rows = []
    return learning_signals(rows)


# ---------------------------------------------------------------------------
# Weekly learning digest (mirrors pace_report.maybe_emit_weekly)
# ---------------------------------------------------------------------------
def build_learning_digest(rows: list[dict]) -> str:
    """A Slack-mrkdwn weekly digest of PACE's track record over ``rows``. Pure.
    Empty string when nothing was logged (the caller then posts nothing)."""
    if not rows:
        return ""
    stats = decision_stats(rows)
    ov = stats["overall"]
    sig = learning_signals(rows)["by_action"]
    lines = [f"*PACE learning digest* — {ov['total']} logged action"
             f"{'s' if ov['total'] != 1 else ''} this week"]
    lines.append(
        f"• {ov['executed']} executed · {ov['approved']} approved · "
        f"{ov['approved_with_modifications']} w/ mods · "
        f"{ov['denied'] + ov['cancelled']} declined · {ov['reverted']} reverted · "
        f"{ov['failed']} failed")
    # Worst-approval action kinds (most declined/reverted), min 2 samples.
    ranked = sorted(
        ((a, s) for a, s in sig.items() if s["total"] >= 2 and s["reject_rate"] > 0),
        key=lambda kv: -kv[1]["reject_rate"])[:3]
    if ranked:
        lines.append("*Most-refused:*")
        for a, s in ranked:
            lines.append(f"• `{a}` — {int(s['reject_rate'] * 100)}% declined/undone "
                         f"({s['denied'] + s['reverted']}/{s['total']})")
    if ov["reverted"]:
        lines.append(f"_⚠️ {ov['reverted']} action(s) were undone after PACE made them — "
                     f"see the PACE Log 'reverted' filter._")
    return "\n".join(lines)


def maybe_emit_weekly_learning(today: Optional[Any] = None) -> dict:
    """Emit ONE learning digest per week on ``pace_audit_digest_weekday``.
    Self-gated on pace_enabled + a configured weekday; best-effort. Called inline
    from the daily scheduler tick (mirrors pace_report.maybe_emit_weekly)."""
    from datetime import date, datetime, timedelta, timezone

    from services import notifications

    if not (settings.pace_enabled and settings.pace_audit_enabled):
        return {"emitted": False, "reason": "disabled"}
    weekday = settings.pace_audit_digest_weekday
    today = today or date.today()
    if weekday is None or today.weekday() != int(weekday):
        return {"emitted": False, "reason": "not_due"}
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        rows = (get_supabase().table("pace_action_log")
                .select("action, client_id, decision, outcome, reverted_at")
                .gte("created_at", since).limit(5000).execute()).data or []
        body = build_learning_digest(rows)
        if not body:
            return {"emitted": False, "reason": "nothing_logged"}
        notifications.emit(
            client_id=None, kind="pace_learning_digest",
            title="PACE learning digest",
            summary=body, severity="info",
            payload={"link": "/pace/log", "slack_channel": settings.pace_slack_channel or None},
            dedupe_key=f"pace_learning_digest:{today.isoformat()}",
        )
        return {"emitted": True, "rows": len(rows)}
    except Exception as exc:
        logger.warning("pace_learning_digest_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error"}
