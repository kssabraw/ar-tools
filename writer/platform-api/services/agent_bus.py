"""Agent-to-agent coordination bus (WS3 — agent-coordination-and-efficiency-plan-v1_0).

A thin DB-backed message/inbox log that makes the agents' handoffs EXPLICIT so
DORA can measure how work flows between SerMaStr / PACE / QA / autonomy and flag
coordination inefficiencies. Not a new decision protocol — agents POST at their
existing seams (approval, capacity-defer, efficiency finding) and DORA reads the
bus in WS4. Gated on ``agent_bus_enabled`` (default False); every post is
additive + best-effort and NEVER raises into a hot path.

Pure helpers (``inbox_filter`` / ``coordination_metrics``) are unit-tested; the
impure ``post`` / ``mark_acted`` / ``inbox`` / ``recent`` wrap Supabase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

AGENTS = ("sermastr", "pace", "qa", "autonomy", "dora")
KINDS = ("handoff", "request", "notice", "blocker", "ack")
# Kinds that represent WORK the recipient owes an action on — the ones whose
# staying open past the stale window is a coordination problem. A 'notice' is
# informational (DORA reads it); an 'ack' closes a thread.
ACTIONABLE_KINDS = ("handoff", "request", "blocker")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def inbox_filter(messages: list[dict], agent: str, *, open_only: bool = True) -> list[dict]:
    """Messages addressed to ``agent`` (or broadcast), newest first. Pure."""
    out = [m for m in (messages or [])
           if m.get("to_agent") in (agent, "broadcast")
           and (not open_only or m.get("status") == "open")]
    return sorted(out, key=lambda m: m.get("created_at") or "", reverse=True)


def _age_hours(created_at, now: datetime) -> Optional[float]:
    if not created_at:
        return None
    try:
        ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600.0
    except Exception:
        return None


def coordination_metrics(messages: list[dict], now: Optional[datetime] = None,
                         stale_hours: Optional[float] = None) -> dict:
    """The coordination-health read over the bus, for DORA (WS4). Pure.

    Returns totals, per-(from→to) pair counts, open **blockers** (capacity /
    dependency walls), **stalled** actionable messages (open handoff/request/
    blocker older than ``stale_hours``), and back-and-forth **loops** (a
    correlation thread with ≥3 messages that changed direction ≥2 times — churn
    rather than a clean handoff). Notices are informational and never count as
    stalled."""
    now = now or datetime.now(timezone.utc)
    stale_hours = stale_hours if stale_hours is not None else settings.agent_bus_stale_hours
    msgs = messages or []
    by_pair: dict[str, int] = {}
    open_blockers: list[dict] = []
    stalled: list[dict] = []
    threads: dict[str, list[dict]] = {}
    open_count = 0
    for m in msgs:
        pair = f"{m.get('from_agent')}→{m.get('to_agent')}"
        by_pair[pair] = by_pair.get(pair, 0) + 1
        corr = m.get("correlation_id")
        if corr:
            threads.setdefault(corr, []).append(m)
        if m.get("status") != "open":
            continue
        open_count += 1
        if m.get("kind") == "blocker":
            open_blockers.append(m)
        if m.get("kind") in ACTIONABLE_KINDS:
            age = _age_hours(m.get("created_at"), now)
            if age is not None and age >= stale_hours:
                stalled.append({"from": m.get("from_agent"), "to": m.get("to_agent"),
                                "kind": m.get("kind"), "subject": m.get("subject"),
                                "ref": m.get("ref"), "age_hours": round(age, 1),
                                "client_id": m.get("client_id")})
    loops = []
    for corr, thread in threads.items():
        if len(thread) < 3:
            continue
        ordered = sorted(thread, key=lambda m: m.get("created_at") or "")
        flips = sum(1 for a, b in zip(ordered, ordered[1:])
                    if a.get("from_agent") != b.get("from_agent"))
        if flips >= 2:
            loops.append({"correlation_id": corr, "messages": len(thread), "flips": flips})
    return {
        "total": len(msgs),
        "open": open_count,
        "by_pair": by_pair,
        "open_blockers": open_blockers,
        "stalled": sorted(stalled, key=lambda s: -s["age_hours"]),
        "loops": loops,
    }


# ---------------------------------------------------------------------------
# Impure I/O (gated + best-effort — never raises)
# ---------------------------------------------------------------------------
def post(*, from_agent: str, to_agent: str, kind: str, client_id: Optional[str] = None,
         subject: Optional[str] = None, body: Optional[str] = None, ref: Optional[str] = None,
         correlation_id: Optional[str] = None, dedupe_key: Optional[str] = None,
         payload: Optional[dict] = None) -> Optional[str]:
    """Post a message to the bus. Gated on ``agent_bus_enabled``; best-effort
    (returns None on any failure/skip). When ``dedupe_key`` is given and an OPEN
    message already carries it, this is a no-op (so a daily re-post is idempotent).
    Returns the new message id, or None."""
    if not settings.agent_bus_enabled:
        return None
    if from_agent not in AGENTS or to_agent not in (*AGENTS, "broadcast") or kind not in KINDS:
        logger.warning("agent_bus_bad_args", extra={"from": from_agent, "to": to_agent, "kind": kind})
        return None
    sb = get_supabase()
    try:
        if dedupe_key:
            existing = (sb.table("agent_messages").select("id")
                        .eq("dedupe_key", dedupe_key).eq("status", "open")
                        .limit(1).execute()).data
            if existing:
                return None
        row = {"from_agent": from_agent, "to_agent": to_agent, "kind": kind,
               "client_id": client_id, "subject": subject, "body": body, "ref": ref,
               "correlation_id": correlation_id, "dedupe_key": dedupe_key,
               "payload": payload or {}}
        resp = sb.table("agent_messages").insert(row).execute()
        data = resp.data or []
        return data[0].get("id") if data else None
    except Exception as exc:
        logger.warning("agent_bus_post_failed",
                       extra={"from": from_agent, "to": to_agent, "kind": kind, "error": str(exc)})
        return None


def mark_acted(*, correlation_id: str, by_agent: str, status: str = "acted") -> int:
    """Close the OPEN messages on a correlation thread (an ack). Best-effort;
    returns how many rows were updated (0 on skip/failure)."""
    if not settings.agent_bus_enabled or not correlation_id:
        return 0
    if status not in ("acted", "read", "dismissed"):
        status = "acted"
    try:
        resp = (get_supabase().table("agent_messages")
                .update({"status": status, "acted_at": datetime.now(timezone.utc).isoformat(),
                         "acted_by": by_agent})
                .eq("correlation_id", correlation_id).eq("status", "open").execute())
        return len(resp.data or [])
    except Exception as exc:
        logger.warning("agent_bus_mark_acted_failed",
                       extra={"correlation_id": correlation_id, "error": str(exc)})
        return 0


def placement_correlation(task_id: str) -> str:
    """Correlation id for a PACE→DORA capacity blocker on a task's placement.
    Shared by the post (pm_assign) and the resolve (task_service) so the two can
    never drift apart. Pure."""
    return f"placement:{task_id}"


def resolve_placement_blocker(task_id: str, *, by_agent: str = "pace") -> int:
    """Close any OPEN capacity blocker for a task once it no longer needs staffing
    (it got assigned, or completed) — so DORA's open-blocker / coordination view
    reflects live reality instead of accumulating resolved walls. Best-effort:
    ``mark_acted`` self-gates on ``agent_bus_enabled`` and swallows errors, and a
    task that never had a blocker simply updates 0 rows. Returns rows closed."""
    if not task_id:
        return 0
    return mark_acted(correlation_id=placement_correlation(task_id), by_agent=by_agent)


def inbox(agent: str, *, open_only: bool = True, limit: int = 100) -> list[dict]:
    """Messages addressed to ``agent`` (or broadcast) for the agent to read on its
    run. Best-effort ([] on error)."""
    if not settings.agent_bus_enabled:
        return []
    try:
        q = (get_supabase().table("agent_messages").select("*")
             .in_("to_agent", [agent, "broadcast"])
             .order("created_at", desc=True).limit(limit))
        if open_only:
            q = q.eq("status", "open")
        return q.execute().data or []
    except Exception as exc:
        logger.warning("agent_bus_inbox_failed", extra={"agent": agent, "error": str(exc)})
        return []


def recent(*, days: int = 30, limit: int = 2000) -> list[dict]:
    """All bus traffic over a window, for DORA's coordination read. Best-effort."""
    if not settings.agent_bus_enabled:
        return []
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        return ((get_supabase().table("agent_messages").select("*")
                 .gte("created_at", since).order("created_at", desc=True)
                 .limit(limit).execute()).data or [])
    except Exception as exc:
        logger.warning("agent_bus_recent_failed", extra={"error": str(exc)})
        return []
