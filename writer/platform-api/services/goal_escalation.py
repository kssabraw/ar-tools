"""Chronic-emergency escalation — the "STILL CRITICAL" loud re-surface.

A campaign goal that is critically behind (status behind/overdue) for weeks goes
QUIET under the normal machinery, which is exactly when it most needs attention:

- the weekly strategist review keeps producing 0 *new* proposals (it already
  proposed everything), so its notification degrades to an indistinguishable
  "N findings" line — a chronic emergency reads the same as a healthy client;
- the scan-over-scan drop alerts stop firing once nothing is *newly* worse, so
  the alert stream falls silent on a goal that is still failing.

This module gives such a goal its own loud voice. A daily sweep tracks each
chronic-behind stint in `goal_escalations` and, once a goal has been behind for
`goal_escalation_chronic_weeks`, emits a **critical** notification (both Slack
and the in-app feed, via the shared notifications service) that leads with how
long it has been behind and carries the latest strategist reasoning — then
re-shouts every `goal_escalation_reescalate_days` while the goal stays critical,
and closes when it recovers.

Mirrors the response-episode verify loop (services/response_episodes.py): a
deterministic daily sweep, escalate-on-a-cadence, best-effort per client. The
pure decision helpers are unit-tested; the sweep isolates the DB reads.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# A goal in one of these statuses is a live emergency worth chasing. `custom`
# goals (status "manual") and no_data/on_track/achieved are never chronic.
CRITICAL_STATUSES = {"behind", "overdue"}

# Human labels for the goal_type when a goal has no explicit label.
_TYPE_LABELS = {
    "keyword_position": "keyword position",
    "keywords_in_top": "keywords in top",
    "organic_clicks": "organic clicks",
    "organic_impressions": "organic impressions",
    "ai_visibility": "AI visibility",
    "maps_pack_presence": "local-pack presence",
}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested — no network)
# ---------------------------------------------------------------------------
def _parse_date(value) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def is_critical(status: Optional[str]) -> bool:
    """Whether a goal's computed status is a live emergency. Pure."""
    return status in CRITICAL_STATUSES


def goal_label(goal_eval: dict) -> str:
    """Display label for a goal — its explicit label, else a humanized type. Pure."""
    label = (goal_eval.get("label") or "").strip()
    if label:
        return label
    gtype = goal_eval.get("goal_type") or ""
    return _TYPE_LABELS.get(gtype, gtype.replace("_", " ")) or "goal"


def initial_behind_since(goal_eval: dict, today: date) -> date:
    """When to say a newly-tracked chronic goal has been behind *since*.

    A goal that never made progress (or is already overdue) has been behind
    since it started measuring — seed from its baseline date so a long-standing
    emergency escalates now instead of waiting out a fabricated future clock. A
    goal that had progress and only recently slipped starts the clock today (we
    can't claim it's been behind longer than we've observed). Pure — never
    returns a future date."""
    prog = goal_eval.get("progress_pct")
    never_progressed = prog is None or prog <= 0
    if goal_eval.get("status") == "overdue" or never_progressed:
        seed = (
            _parse_date(goal_eval.get("baseline_date"))
            or _parse_date(goal_eval.get("created_at"))
            or today
        )
        return min(seed, today)
    return today


def weeks_behind(behind_since: Optional[date], today: date) -> int:
    """Whole weeks a goal has been behind. Pure."""
    if not behind_since:
        return 0
    return max(0, (today - behind_since).days // 7)


def should_escalate(row: dict, today: date, chronic_weeks: int, reescalate_days: int) -> bool:
    """Whether an open escalation row is due to (re-)shout: it has been behind
    at least `chronic_weeks`, and either has never escalated or the last
    escalation is at least `reescalate_days` old. Pure."""
    weeks = weeks_behind(_parse_date(row.get("behind_since")), today)
    if weeks < chronic_weeks:
        return False
    last = _parse_ts(row.get("last_escalated_at"))
    if last is None:
        return True
    return (today - last.date()).days >= reescalate_days


def build_escalation(
    client_name: str, goal_eval: dict, weeks: int, alert_count: int, reasoning: Optional[str]
) -> dict:
    """The {title, summary} for a chronic-goal escalation notification. Pure.

    Leads with how long the goal has been behind and the gap to target, folds in
    open-alert context (or explicitly notes their absence — the whole point is
    the goal stays loud even when the alert stream has gone quiet), then carries
    the latest strategist reasoning."""
    label = goal_label(goal_eval)
    status = goal_eval.get("status") or "behind"
    cur = goal_eval.get("current_value")
    tgt = goal_eval.get("effective_target")
    gap = f" — now {cur:g} vs target {tgt:g}" if (cur is not None and tgt is not None) else ""

    title = f"STILL CRITICAL (week {weeks}): {client_name or 'client'} — {label}"
    lead = (
        f'"{label}" has been {status} for {weeks} week{"s" if weeks != 1 else ""}{gap}.'
    )
    if alert_count:
        lead += f" {alert_count} open alert{'s' if alert_count != 1 else ''}."
    else:
        lead += " No fresh alerts have fired — but the goal is still critically behind."
    parts = [lead]
    reasoning = (reasoning or "").strip()
    if reasoning:
        parts.append(reasoning)
    return {"title": title[:200], "summary": " ".join(parts)}


# ---------------------------------------------------------------------------
# Impure reads
# ---------------------------------------------------------------------------
def _clients_with_active_goals(supabase) -> list[str]:
    rows = (
        supabase.table("campaign_goals").select("client_id").eq("active", True).execute()
    ).data or []
    seen: list[str] = []
    known: set[str] = set()
    for r in rows:
        cid = r.get("client_id")
        if cid and cid not in known:
            known.add(cid)
            seen.append(cid)
    return seen


def _open_escalations(supabase, client_id: str) -> dict[str, dict]:
    rows = (
        supabase.table("goal_escalations").select("*")
        .eq("client_id", client_id).eq("status", "open").execute()
    ).data or []
    return {r["goal_id"]: r for r in rows}


def _client_name(supabase, client_id: str) -> str:
    try:
        rows = (
            supabase.table("clients").select("name").eq("id", client_id).limit(1).execute()
        ).data
        return (rows[0].get("name") if rows else "") or ""
    except Exception:
        return ""


def _latest_reasoning(supabase, client_id: str) -> Optional[str]:
    """The most recent completed strategist review's assessment — the current,
    already-computed weekly reasoning (it leads with the critical goal). Trimmed;
    best-effort (None when there's no review to quote)."""
    try:
        rows = (
            supabase.table("strategy_reviews").select("assessment")
            .eq("client_id", client_id).eq("status", "complete")
            .order("created_at", desc=True).limit(1).execute()
        ).data
    except Exception:
        return None
    if not rows:
        return None
    text = (rows[0].get("assessment") or "").strip()
    if not text:
        return None
    return text[:400] + ("…" if len(text) > 400 else "")


def _open_alert_count(supabase, client_id: str) -> int:
    """Count of the client's currently-open drop alerts (context for the brief)."""
    total = 0
    for table in ("rank_alerts", "maps_alerts"):
        try:
            res = (
                supabase.table(table).select("id", count="exact")
                .eq("client_id", client_id).is_("resolved_at", "null").execute()
            )
            total += res.count or 0
        except Exception:
            continue
    return total


# ---------------------------------------------------------------------------
# Daily sweep (shared scheduler)
# ---------------------------------------------------------------------------
def run_goal_escalation_sweep() -> dict:
    """Daily: open / re-escalate / resolve chronic-goal escalations across all
    clients. Best-effort per client — one bad client never stops the sweep."""
    stats = {"opened": 0, "escalated": 0, "resolved": 0, "clients": 0}
    if not settings.goal_escalation_enabled:
        return stats
    supabase = get_supabase()
    today = date.today()
    now = datetime.now(timezone.utc)
    try:
        client_ids = _clients_with_active_goals(supabase)
    except Exception as exc:
        logger.error("goal_escalation.list_clients_failed", extra={"error": str(exc)})
        return stats

    for client_id in client_ids:
        try:
            _sweep_client(supabase, client_id, today, now, stats)
            stats["clients"] += 1
        except Exception as exc:
            logger.warning(
                "goal_escalation.client_failed",
                extra={"client_id": client_id, "error": str(exc)},
            )

    if stats["opened"] or stats["escalated"] or stats["resolved"]:
        logger.info("goal_escalation.sweep_complete", extra=stats)
    return stats


def _sweep_client(supabase, client_id: str, today: date, now: datetime, stats: dict) -> None:
    from services import campaign_goals

    goals = campaign_goals.assess_goals(client_id, today)
    critical = {
        g["id"]: g
        for g in goals
        if is_critical(g.get("status")) and g.get("goal_type") != "custom"
    }
    open_rows = _open_escalations(supabase, client_id)
    client_name: Optional[str] = None

    # 1) Open a row for every newly-critical goal; (re-)escalate the due ones.
    for gid, g in critical.items():
        row = open_rows.get(gid)
        if row is None:
            row = _insert_escalation(supabase, client_id, g, initial_behind_since(g, today))
            if row is None:
                continue
            stats["opened"] += 1
        else:
            _refresh_row(supabase, row, g)

        if should_escalate(
            row, today,
            settings.goal_escalation_chronic_weeks,
            settings.goal_escalation_reescalate_days,
        ):
            weeks = weeks_behind(_parse_date(row.get("behind_since")), today)
            if client_name is None:
                client_name = _client_name(supabase, client_id)
            note = build_escalation(
                client_name, g, weeks,
                _open_alert_count(supabase, client_id),
                _latest_reasoning(supabase, client_id),
            )
            notifications.emit(
                client_id=client_id,
                kind="goal_chronic",
                title=note["title"],
                summary=note["summary"],
                severity="critical",
                payload={
                    "link": f"clients/{client_id}/goals",
                    "goal_id": gid,
                    "weeks_behind": weeks,
                },
            )
            supabase.table("goal_escalations").update(
                {
                    "last_escalated_at": now.isoformat(),
                    "escalation_count": (row.get("escalation_count") or 0) + 1,
                    "updated_at": now.isoformat(),
                }
            ).eq("id", row["id"]).execute()
            stats["escalated"] += 1

    # 2) Resolve open rows whose goal is no longer critical.
    for gid, row in open_rows.items():
        if gid in critical:
            continue
        supabase.table("goal_escalations").update(
            {"status": "resolved", "resolved_at": now.isoformat(), "updated_at": now.isoformat()}
        ).eq("id", row["id"]).execute()
        stats["resolved"] += 1
        # Only announce recovery for a goal we actually shouted about, so a row
        # that flickered critical without ever escalating closes silently.
        if row.get("escalation_count"):
            notifications.emit(
                client_id=client_id,
                kind="goal_recovered",
                title=f"No longer critical: {row.get('goal_label') or 'goal'}",
                summary="A goal that had been chronically behind is no longer in a "
                "critical state — the standing escalation is closed.",
                severity="info",
                payload={"link": f"clients/{client_id}/goals", "goal_id": gid},
            )


def _insert_escalation(supabase, client_id: str, goal_eval: dict, behind_since: date) -> Optional[dict]:
    cur = goal_eval.get("current_value")
    try:
        res = (
            supabase.table("goal_escalations").insert(
                {
                    "client_id": client_id,
                    "goal_id": goal_eval["id"],
                    "goal_label": goal_label(goal_eval),
                    "goal_type": goal_eval.get("goal_type"),
                    "behind_since": behind_since.isoformat(),
                    "baseline_value": goal_eval.get("baseline_value"),
                    "target_value": goal_eval.get("effective_target"),
                    "current_value": cur,
                    "worst_value": cur,
                }
            ).execute()
        ).data
        return res[0] if res else None
    except Exception as exc:
        logger.warning(
            "goal_escalation.insert_failed",
            extra={"client_id": client_id, "goal_id": goal_eval.get("id"), "error": str(exc)},
        )
        return None


def _refresh_row(supabase, row: dict, goal_eval: dict) -> None:
    """Update the current value and track the worst (most-behind) point seen."""
    cur = goal_eval.get("current_value")
    if cur is None:
        return
    updates: dict = {"current_value": cur, "updated_at": datetime.now(timezone.utc).isoformat()}
    worst = row.get("worst_value")
    lower_is_better = goal_eval.get("goal_type") == "keyword_position"
    if worst is None:
        updates["worst_value"] = cur
    elif (cur > worst) if lower_is_better else (cur < worst):
        updates["worst_value"] = cur
    try:
        supabase.table("goal_escalations").update(updates).eq("id", row["id"]).execute()
    except Exception:
        pass  # a missed refresh self-heals next sweep
