"""PACE — identity & authorization model (Phase 1).

docs/modules/project-manager-agent-plan-v1_0.md §3. The permission foundation
the PACE actions (Phase 2) enforce. This module is intentionally self-contained
and does **not** rewire the live SerMaStr `interpret()`/`_pending` flow — that
wiring lands with the actual PACE actions in Phase 2, where it's testable
end-to-end and can't destabilise the already-enabled assistant.

What's here:
- ``ActionContext`` — the resolved actor for a turn (who + role + source).
- The **role → action matrix** (`min_role_for` / `can` / `require`), grounded in
  the suite's real roles (`client < team_member < staff < admin`). The two
  "via policy" cells are config-driven (`pace_perm_*`).
- **Resolvers**: `context_from_auth` (web JWT) and `resolve_slack_actor` (Slack
  user id → profile via `profiles.slack_user_id`; anonymous when unmapped).
- **Actor-bound confirmation** helper (`confirm_actor_ok`) — the person who
  confirms a staged action must be the one who staged it (admin takeover
  excepted). Pure; Phase 2 stores the requester on `_pending` and calls this.

Pure logic is unit-tested; the one DB read (`resolve_slack_actor`) is mockable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import role_rank

# Static role→action matrix (min role). The two config-driven cells are resolved
# live in ``min_role_for`` so they honour policy overrides / test monkeypatches.
_MATRIX: dict[str, str] = {
    "read_own_tasks": "team_member",
    "update_own_status": "team_member",
    "nudge_self": "team_member",
    "set_task_due_own": "team_member",
    "nudge_other": "staff",
    "reassign_task": "staff",
    "assign_task": "staff",           # v1.3 workload-aware auto-placement (§4.6)
    "generate_pace_report": "staff",  # v1.3 delivery report (§4.7) — read-only
    "set_task_due_other": "staff",
    "unblock_task": "staff",
    # "read_board" and "generate_client_month" are policy-driven (see below).
}


@dataclass
class ActionContext:
    """The resolved actor for one turn."""
    profile_id: Optional[str]
    role: Optional[str]
    slack_user_id: Optional[str] = None
    channel: Optional[str] = None
    source: str = "web"  # 'web' | 'slack' | 'system'

    @property
    def is_anonymous(self) -> bool:
        """No known suite profile behind this actor (e.g. an unlinked Slack
        user). Anonymous actors may read per channel policy but can perform no
        role-gated action."""
        return not self.profile_id


# System context for scheduled/automated work (full trust; e.g. the scheduled
# monthly generation records a null/system actor).
SYSTEM_CONTEXT = ActionContext(profile_id=None, role="admin", source="system")


def min_role_for(action: str) -> Optional[str]:
    """The minimum role for an action, honouring the config-driven policy cells.
    Unknown actions default to ``staff`` (fail safe — a new write isn't open to
    VAs by accident)."""
    if action == "read_board":
        return settings.pace_perm_read_board_min_role
    if action == "generate_client_month":
        return settings.pace_perm_generate_month_min_role
    return _MATRIX.get(action, "staff")


def can(context: ActionContext, action: str) -> bool:
    """True when ``context`` is authorized for ``action``. A system context is
    always allowed; an anonymous actor never is; otherwise compare role rank."""
    if context.source == "system":
        return True
    if context.is_anonymous:
        return False
    minimum = min_role_for(action)
    return role_rank(context.role) >= role_rank(minimum)


def require(context: ActionContext, action: str) -> tuple[bool, Optional[str]]:
    """(ok, reason) — a human-readable refusal reason when not allowed. Phase 2
    calls this at **stage** time so an unauthorized ask is refused before any
    confirm."""
    if can(context, action):
        return True, None
    if context.is_anonymous:
        if context.source == "slack":
            return False, "Link your Slack account first (an admin can do it on the Team page)."
        return False, "You need to be signed in to do that."
    return False, f"That needs the *{min_role_for(action)}* role or higher — ask an admin."


def confirm_actor_ok(requester_profile_id: Optional[str], confirmer: ActionContext) -> bool:
    """Actor-bound confirmation (§3.3): only the person who staged an action may
    confirm it — an admin may take over. Pure. (Phase 2 stores the requester's
    profile_id on the pending entry and calls this on 'yes'.)"""
    if confirmer.role == "admin":
        return True
    return bool(requester_profile_id) and requester_profile_id == confirmer.profile_id


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------
def context_from_auth(auth: dict, *, source: str = "web") -> ActionContext:
    """Build a context from the web JWT auth dict (`{user_id, role}`)."""
    return ActionContext(
        profile_id=auth.get("user_id"),
        role=auth.get("role"),
        source=source,
    )


def resolve_slack_actor(slack_user_id: Optional[str], channel: Optional[str] = None) -> ActionContext:
    """Slack user id → ActionContext via `profiles.slack_user_id`. An unmapped
    (or missing) Slack user resolves to an **anonymous** Slack context (reads
    per channel policy; all role-gated actions refused)."""
    if not slack_user_id:
        return ActionContext(profile_id=None, role=None, slack_user_id=slack_user_id,
                             channel=channel, source="slack")
    try:
        rows = (
            get_supabase()
            .table("profiles")
            .select("id, role")
            .eq("slack_user_id", slack_user_id)
            .limit(1)
            .execute()
        ).data
    except Exception:
        rows = None
    if rows:
        return ActionContext(profile_id=rows[0]["id"], role=rows[0].get("role"),
                             slack_user_id=slack_user_id, channel=channel, source="slack")
    return ActionContext(profile_id=None, role=None, slack_user_id=slack_user_id,
                         channel=channel, source="slack")
