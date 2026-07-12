"""PACE v1.4 Phase 9 — follow-through episodes: the chase loop (§4.9).

The single most PM-like piece: PACE previously flagged and forgot. Every
pm_signals condition (stale / overdue / unassigned / unacted producer task) now
opens a **task_episode** with a clock, the `response_episodes` pattern:

- **Open** when the signal is first detected; one OPEN episode per (task, kind).
- **Movement** = any `task_activity` beyond {created, placement_deferred} since
  the episode opened (exclude-list, so unknown kinds count as movement — fail
  toward NOT escalating someone publicly). Movement resets the escalation clock.
- **Chase** (aggressive, owner ruling): while open, the registered generator
  contributes a proposal to every daily Chase Plan (`pace_chase_renudge_days`
  gates re-proposals; default 1 = daily). Nudges for assigned work — hygiene
  wording for long-In-Progress ("confirm it's actually in progress") — and
  auto-place proposals for unassigned/unacted work.
- **Escalate once, publicly**: after `pace_chase_escalate_business_days`
  business days with no movement (including nobody confirming any plan), ONE
  Tier-0 channel post names the task, assignee, client, and days stuck. Never
  re-escalates; the episode stays open (and keeps being chased) until resolved.
- **Resolve** when the signal clears — the tracker's call, not a heuristic
  (status moved, assignee set, task completed/trashed all clear their signals).

`run_episode_sync` rides the daily scheduler tick immediately before the Chase
Plan build. Pure helpers (business-day math, open/resolve/escalate selection)
are unit-tested; DB reads/writes are thin and batched.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, pm_signals
from services.pace_proposals import register_generator

logger = logging.getLogger(__name__)

EPISODE_KINDS = ("stale", "overdue", "unassigned", "unacted")
# Activity kinds that do NOT count as movement (everything else does — unknown
# kinds fail toward "moved", i.e. toward not publicly escalating).
_NON_MOVEMENT_KINDS = {"created", "placement_deferred"}

_PRIORITY = {"unacted": 80, "overdue": 70, "stale": 60, "unassigned": 50}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def business_days_between(start: date, end: date) -> int:
    """Business days (Mon–Fri, no holidays — §2b convention) in (start, end].
    Zero when end <= start. Pure."""
    if end <= start:
        return 0
    days, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _ts_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def signal_keys(clients: list[dict]) -> dict[tuple, dict]:
    """Flatten a board digest into {(task_id, kind): info} for the four episode
    kinds. info carries what the chase generator needs. Pure."""
    out: dict[tuple, dict] = {}
    for c in clients:
        cid = c.get("client_id")
        for t in c.get("stale") or []:
            out[(t["id"], "stale")] = {**t, "client_id": cid}
        for t in c.get("overdue") or []:
            out[(t["id"], "overdue")] = {**t, "client_id": cid}
        for t in c.get("unassigned") or []:
            out[(t["id"], "unassigned")] = {**t, "client_id": cid}
        for t in c.get("unacted_producer") or []:
            out[(t["id"], "unacted")] = {**t, "client_id": cid}
    return out


def should_escalate(episode: dict, today: date, threshold_business_days: int) -> bool:
    """One public escalation per episode: not yet escalated AND the clock —
    anchored at the latest movement, else the episode's opening — has run
    ≥ threshold business days. Pure."""
    if episode.get("escalated_at") or episode.get("status") != "open":
        return False
    anchor = _ts_date(episode.get("last_movement_at")) or _ts_date(episode.get("opened_at"))
    if not anchor:
        return False
    return business_days_between(anchor, today) >= threshold_business_days


def due_for_proposal(episode: dict, today: date, renudge_days: int) -> bool:
    """Whether the chase generator should propose for this episode today
    (`pace_chase_renudge_days` pacing; never-proposed ⇒ due). Pure."""
    last = _ts_date(episode.get("last_proposed_at"))
    return last is None or (today - last).days >= max(1, renudge_days)


def stuck_days(episode: dict, today: date) -> int:
    anchor = _ts_date(episode.get("last_movement_at")) or _ts_date(episode.get("opened_at"))
    return business_days_between(anchor, today) if anchor else 0


# ---------------------------------------------------------------------------
# DB thin layer
# ---------------------------------------------------------------------------
def _open_episodes() -> list[dict]:
    return (
        get_supabase().table("task_episodes").select("*").eq("status", "open").execute()
    ).data or []


def _latest_movement(task_ids: list[str]) -> dict[str, str]:
    """Latest movement-counting activity timestamp per task (batched)."""
    if not task_ids:
        return {}
    rows = (
        get_supabase().table("task_activity")
        .select("task_id, kind, created_at")
        .in_("task_id", task_ids)
        .execute()
    ).data or []
    latest: dict[str, str] = {}
    for r in rows:
        if r.get("kind") in _NON_MOVEMENT_KINDS:
            continue
        ts = r.get("created_at") or ""
        if ts > latest.get(r["task_id"], ""):
            latest[r["task_id"]] = ts
    return latest


def _client_names(client_ids: list) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


# ---------------------------------------------------------------------------
# Daily sync (scheduler, before the Chase Plan build)
# ---------------------------------------------------------------------------
def run_episode_sync(today: Optional[date] = None) -> dict:
    """Open / resolve / clock / escalate. Self-gated; best-effort per step."""
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return {"synced": False, "reason": "disabled"}
    today = today or date.today()
    sb = get_supabase()

    digest = pm_signals.build_board_digest(None)
    signals = signal_keys(digest.get("clients") or [])
    open_eps = _open_episodes()
    open_keys = {(e["task_id"], e["kind"]): e for e in open_eps}

    # 1) Open new episodes for newly-detected signals.
    opened = 0
    for key in signals.keys() - open_keys.keys():
        try:
            sb.table("task_episodes").insert(
                {"task_id": key[0], "kind": key[1]}
            ).execute()
            opened += 1
        except Exception as exc:  # unique-index race with a concurrent sync → no-op
            logger.warning("episode_open_failed", extra={"key": str(key), "error": str(exc)})

    # 2) Resolve episodes whose signal cleared (the tracker's call).
    resolved_ids = [e["id"] for k, e in open_keys.items() if k not in signals]
    if resolved_ids:
        sb.table("task_episodes").update(
            {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat()}
        ).in_("id", resolved_ids).execute()

    # 3) Movement clock for the still-open set.
    still_open = [e for k, e in open_keys.items() if k in signals]
    movement = _latest_movement(sorted({e["task_id"] for e in still_open}))
    for e in still_open:
        ts = movement.get(e["task_id"])
        if ts and ts > (e.get("opened_at") or "") and ts != e.get("last_movement_at"):
            sb.table("task_episodes").update({"last_movement_at": ts}).eq("id", e["id"]).execute()
            e["last_movement_at"] = ts

    # 4) Single public escalation per exhausted episode (batched into one post).
    threshold = settings.pace_chase_escalate_business_days
    to_escalate = [e for e in still_open if should_escalate(e, today, threshold)]
    if to_escalate:
        names = _client_names([signals[(e["task_id"], e["kind"])].get("client_id") for e in to_escalate])
        lines = []
        for e in to_escalate:
            info = signals[(e["task_id"], e["kind"])]
            who = info.get("assignee_name") or "unassigned"
            lines.append(
                f"• “{info.get('name')}” ({names.get(info.get('client_id'), 'client')}) — "
                f"{who}, {e['kind']} with no movement for {stuck_days(e, today)} business days"
            )
        notifications.emit(
            client_id=None, kind="pace_escalation",
            title=f"PACE escalation — {len(to_escalate)} item{'s' if len(to_escalate) != 1 else ''} "
                  f"stuck ≥{threshold} business days with nobody acting",
            summary="\n".join(lines), severity="warning",
            payload={"link": "/tasks", "slack_channel": settings.pace_slack_channel or None},
            dedupe_key=f"pace_escalation:{today.isoformat()}",
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        sb.table("task_episodes").update({"escalated_at": now_iso}).in_(
            "id", [e["id"] for e in to_escalate]
        ).execute()

    return {"synced": True, "opened": opened, "resolved": len(resolved_ids),
            "escalated": len(to_escalate), "open": len(still_open) + opened}


# ---------------------------------------------------------------------------
# Chase Plan generator (registered)
# ---------------------------------------------------------------------------
@register_generator
def episode_chase_proposals(today: date) -> list[dict]:
    """One proposal per open, due-for-renudge episode. Assigned work → a nudge
    (hygiene wording for long-In-Progress); unassigned/unacted → auto-place."""
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return []
    eps = (
        get_supabase().table("task_episodes")
        .select("*, tasks(name, assignee_gid, assignee_name, status_key, client_id, completed, deleted_at)")
        .eq("status", "open")
        .execute()
    ).data or []
    renudge = settings.pace_chase_renudge_days
    names = _client_names([(e.get("tasks") or {}).get("client_id") for e in eps])
    proposals, proposed_ids = [], []
    for e in eps:
        t = e.get("tasks") or {}
        if not t or t.get("completed") or t.get("deleted_at"):
            continue  # sync will resolve it; don't chase a closed task
        if not due_for_proposal(e, today, renudge):
            continue
        client_id = t.get("client_id")
        if not client_id:
            continue
        client_name = names.get(client_id, "client")
        days = stuck_days(e, today)
        task_name = t.get("name") or ""
        if e["kind"] in ("unassigned", "unacted") or not t.get("assignee_gid"):
            proposals.append({
                "action": "assign_task", "client_id": client_id, "client_name": client_name,
                "args": {"task_name": task_name},
                "reason": f"Place “{task_name}” — {e['kind']} {days}d, nobody owns it",
                "priority": _PRIORITY.get(e["kind"], 50), "kind": "chase_place",
                "perm": "assign_task",
            })
        else:
            who = t.get("assignee_name") or "the assignee"
            if e["kind"] == "stale":
                why = (f"stuck in {t.get('status_key')} {days} business days — "
                       f"ask {who} to move it or confirm the status is real")
            else:
                why = f"overdue — remind {who}"
            proposals.append({
                "action": "nudge_assignee", "client_id": client_id, "client_name": client_name,
                "args": {"task_name": task_name},
                "reason": f"Nudge {who} — “{task_name}” {why}",
                "priority": _PRIORITY.get(e["kind"], 50), "kind": "chase_nudge",
                "perm": "nudge_other",
            })
        proposed_ids.append(e["id"])
    if proposed_ids:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            sb = get_supabase()
            for eid in proposed_ids:
                cur = next(x for x in eps if x["id"] == eid)
                sb.table("task_episodes").update(
                    {"last_proposed_at": now_iso, "nudge_count": (cur.get("nudge_count") or 0) + 1}
                ).eq("id", eid).execute()
        except Exception as exc:
            logger.warning("episode_propose_stamp_failed", extra={"error": str(exc)})
    return proposals
