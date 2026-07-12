"""PACE v1.4 Phase 13 — per-person morning DM briefs (§4.13).

The §4.4 personal brief, PUSHED: every workday morning each linked roster
member gets their own overdue / due-today / this-week list as a Slack DM
(chat.postMessage to their user id — requires the Slack app's ``im:write``
scope). Tier 0 — a read, no confirm. Gated on `pace_enabled` +
`pace_initiative_enabled` + `pace_daily_brief_push` (default off until the
scope is granted).

Routing: member → `asana_team_members.profile_id` → `profiles.slack_user_id`.
Unlinked members are skipped and counted in the day's arbiter notification
("N unreachable — link them on the Team page"). A missing ``im:write`` scope
degrades to logged-once silence — never channel spam, never a daily error
storm. Members with nothing open get no DM (no noise).

Once-per-day across restarts via the arbiter notification's unique dedupe_key
(the Chase Plan pattern).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications, task_service

logger = logging.getLogger(__name__)

_MAX_LINES_PER_BUCKET = 6
# Slack errors that mean "DMs aren't provisioned" (missing im:write etc.) —
# logged once per process, then silent.
_SCOPE_ERRORS = ("missing_scope", "not_allowed_token_type", "invalid_auth")
_scope_warning_logged = False


# ---------------------------------------------------------------------------
# Pure (unit-tested)
# ---------------------------------------------------------------------------
def build_brief_text(tasks: list[dict], client_names: dict, today: date) -> Optional[str]:
    """One member's morning brief from their open tasks; None when they have
    nothing overdue / due today / due this week (no noise). Pure."""
    if not tasks:
        return None
    buckets = task_service.bucket_by_due(tasks, today)
    sections = []
    for key, label in (("overdue", "Overdue"), ("today", "Due today"), ("this_week", "This week")):
        rows = buckets.get(key) or []
        if not rows:
            continue
        lines = [f"*{label}:*"]
        for t in rows[:_MAX_LINES_PER_BUCKET]:
            client = client_names.get(t.get("client_id"), "client")
            due = f" (due {t['due_date']})" if key == "this_week" and t.get("due_date") else ""
            lines.append(f"• {t.get('name')} — {client}{due}")
        if len(rows) > _MAX_LINES_PER_BUCKET:
            lines.append(f"…and {len(rows) - _MAX_LINES_PER_BUCKET} more")
        sections.append("\n".join(lines))
    if not sections:
        return None
    return "☀️ *Your day at a glance*\n" + "\n".join(sections)


# ---------------------------------------------------------------------------
# The push
# ---------------------------------------------------------------------------
def _linked_members() -> list[dict]:
    """Active members with a full Slack route (profile link + slack_user_id),
    plus the unreachable count."""
    sb = get_supabase()
    members = (
        sb.table("asana_team_members").select("gid, name, profile_id")
        .eq("active", True).execute()
    ).data or []
    profile_ids = [m["profile_id"] for m in members if m.get("profile_id")]
    slack_by_profile: dict = {}
    if profile_ids:
        for p in (sb.table("profiles").select("id, slack_user_id")
                  .in_("id", profile_ids).execute()).data or []:
            if p.get("slack_user_id"):
                slack_by_profile[p["id"]] = p["slack_user_id"]
    for m in members:
        m["slack_user_id"] = slack_by_profile.get(m.get("profile_id"))
    return members


async def run_morning_briefs(today: Optional[date] = None) -> dict:
    """Send each linked member their brief. Self-gated; weekdays only;
    once/day via the arbiter notification's dedupe_key; best-effort per DM."""
    global _scope_warning_logged
    if not (settings.pace_enabled and settings.pace_initiative_enabled
            and settings.pace_daily_brief_push):
        return {"sent": 0, "reason": "disabled"}
    if not settings.slack_bot_token:
        return {"sent": 0, "reason": "no_slack"}
    today = today or date.today()
    if today.weekday() >= 5:
        return {"sent": 0, "reason": "weekend"}

    members = _linked_members()
    linked = [m for m in members if m.get("slack_user_id")]
    unreachable = len(members) - len(linked)

    # Once-per-day arbiter (also surfaces the unreachable count in-app).
    nid = notifications.emit(
        client_id=None, kind="pace_briefs",
        title=f"Morning briefs — {len(linked)} member{'s' if len(linked) != 1 else ''} briefed"
              + (f", {unreachable} unreachable (link them on the Team page)" if unreachable else ""),
        summary=None, severity="info",
        payload={"link": "/workload", "skip_channels": ["slack"]},
        dedupe_key=f"pace_briefs:{today.isoformat()}",
    )
    if nid is None:
        return {"sent": 0, "reason": "deduped"}
    if not linked:
        return {"sent": 0, "reason": "nobody_linked", "unreachable": unreachable}

    rows = (
        get_supabase().table("tasks")
        .select("id, client_id, name, due_date, assignee_gid")
        .in_("assignee_gid", [m["gid"] for m in linked])
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or []
    by_gid: dict[str, list[dict]] = {}
    for r in rows:
        by_gid.setdefault(r["assignee_gid"], []).append(r)
    client_ids = sorted({r["client_id"] for r in rows if r.get("client_id")})
    client_names = {}
    if client_ids:
        for c in (get_supabase().table("clients").select("id, name")
                  .in_("id", client_ids).execute()).data or []:
            client_names[c["id"]] = c.get("name")

    from services.slack_assistant import post_message

    sent = 0
    for m in linked:
        text = build_brief_text(by_gid.get(m["gid"], []), client_names, today)
        if not text:
            continue
        try:
            await post_message(m["slack_user_id"], text)
            sent += 1
        except Exception as exc:
            msg = str(exc)
            if any(code in msg for code in _SCOPE_ERRORS):
                if not _scope_warning_logged:
                    logger.warning("pace_briefs_dm_unavailable",
                                   extra={"error": msg, "hint": "grant im:write + reinstall"})
                    _scope_warning_logged = True
                break  # scope problem hits everyone — stop, stay silent
            logger.warning("pace_brief_dm_failed", extra={"member": m.get("name"), "error": msg})
    return {"sent": sent, "linked": len(linked), "unreachable": unreachable}
