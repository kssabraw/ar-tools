"""PACE v1.4 Phase 8 — the proposal engine + daily Chase Plan (§4.8).

The structural shift from coordinator to manager: PACE gains INITIATIVE. A
registry of generators (episodes §4.9, triage §4.10, rebalance §4.11, slips
§4.12) produces the actions PACE *wants* to take; this engine batches them into
ONE daily Chase Plan message. Every actionable item is a standard staged
`PACE_ACTIONS` action — target-resolved at build time — and executes only on a
human's selective confirm in the plan's Slack thread (reply *yes* for all, or
`yes 1,3`). Owner rulings (2026-07-12): initiate-only (no Tier-1 auto-execution
— the per-kind `pace_autonomy` config exists for a future graduation and forks
here), aggressive cadence, public escalation.

Authorization model: items are staged under SYSTEM_CONTEXT (there is no human
requester at build time), each carrying the matrix `min_role` for its action;
the CONFIRMER is authorized per selected item at confirm time (an anonymous
Slack user confirms nothing). One confirm consumes the whole plan — selected
items run, unselected are dropped and simply re-proposed by their generators
tomorrow (the aggressive cadence makes that the correct semantics). An
unconfirmed plan is superseded by the next day's plan, never executed late.

Delivery: the confirmable copy is posted directly to Slack (PACE channel when
set, else the default channel) so its `ts` keys the batch pending entry in the
assistant's store; an in-app notification copy (Tier 0) rides the notifications
service with `skip_channels=["slack"]` so the channel doesn't get two copies —
its unique `dedupe_key` is also the once-per-day arbiter.
"""

from __future__ import annotations

import inspect
import logging
from datetime import date
from typing import Callable, Optional

from config import settings
from services import notifications, pace_auth
from services.pace_actions import PACE_ACTIONS
from services.pace_auth import SYSTEM_CONTEXT, ActionContext

logger = logging.getLogger(__name__)

# Generators: (today) -> list[proposal dict]. Registered by phases 9–12; each is
# best-effort (a failing generator never breaks the plan). A proposal:
#   {action, client_id, client_name, args, reason, priority, kind, perm}
# - action: PACE_ACTIONS key; args: the raw stage() input
# - reason: the human line shown in the plan
# - kind:   pace_autonomy lookup key (e.g. "nudge", "triage_place")
# - perm:   pace_auth matrix key deciding who may confirm it
PROPOSAL_GENERATORS: list[Callable] = []


def register_generator(fn: Callable) -> Callable:
    PROPOSAL_GENERATORS.append(fn)
    return fn


# ---------------------------------------------------------------------------
# Pure: reply parsing + rendering (unit-tested)
# ---------------------------------------------------------------------------
def parse_plan_reply(text: str, n_items: int) -> Optional[list[int]]:
    """Which plan items (1-based) does a reply approve? None ⇒ not an approval
    (leave the plan pending). Bare affirmative ⇒ all. "yes 1,3" / "approve 2" /
    "yes 1-3" ⇒ that subset (out-of-range dropped; empty subset ⇒ None). Pure."""
    from services.slack_assistant.helpers import is_affirmative

    t = (text or "").strip().lower().rstrip("!.")
    if not t or n_items <= 0:
        return None
    head, _, rest = t.partition(" ")
    if head in {"yes", "approve", "confirm", "ok", "okay"} and rest:
        picks: list[int] = []
        numeric = True
        for chunk in rest.replace(",", " ").split():
            if "-" in chunk:
                a, _, b = chunk.partition("-")
                if a.isdigit() and b.isdigit():
                    picks.extend(range(int(a), int(b) + 1))
                else:
                    numeric = False
                    break
            elif chunk.isdigit():
                picks.append(int(chunk))
            else:
                numeric = False  # "yes please do it" — a phrase, not an index list
                break
        if numeric:
            picks = sorted({p for p in picks if 1 <= p <= n_items})
            return picks or None  # explicit picks all out of range ⇒ not approved
    if is_affirmative(t):
        return list(range(1, n_items + 1))
    return None


def render_plan(plan: dict) -> str:
    """The Chase Plan message (Slack mrkdwn). Pure."""
    items = plan.get("items") or []
    lines = [
        f"*PACE chase plan — {len(items)} proposed action{'s' if len(items) != 1 else ''}* "
        f"(reply *yes* for all, or `yes 1,3` to pick)"
    ]
    for it in items:
        lines.append(f"{it['index']}. {it['reason']} — _{it['client_name']}_")
    for done in plan.get("auto_results") or []:
        lines.append(f"• ✅ (auto) {done}")
    for flag in plan.get("flags") or []:
        lines.append(f"• ⚠️ {flag}")
    if plan.get("overflow"):
        lines.append(f"…and {plan['overflow']} lower-priority items held for tomorrow.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Build (impure: runs generators + stages items)
# ---------------------------------------------------------------------------
async def _call_action(fn, *args):
    out = fn(*args)
    if inspect.isawaitable(out):
        out = await out
    return out


async def build_chase_plan(today: Optional[date] = None) -> dict:
    """Collect → rank → cap → stage. Returns {date, items, auto_results, flags,
    overflow}. Items carry the staged args + min_role for confirm-time checks."""
    today = today or date.today()
    proposals: list[dict] = []
    for gen in PROPOSAL_GENERATORS:
        try:
            proposals.extend(gen(today) or [])
        except Exception as exc:  # one bad generator never kills the plan
            logger.warning("chase_plan_generator_failed",
                           extra={"generator": getattr(gen, "__name__", "?"), "error": str(exc)})
    proposals.sort(key=lambda p: -(p.get("priority") or 0))
    overflow = max(0, len(proposals) - settings.pace_chase_max_items)
    proposals = proposals[: settings.pace_chase_max_items]

    items, auto_results, flags = [], [], []
    autonomy = settings.pace_autonomy or {}
    for p in proposals:
        action = p.get("action")
        meta = PACE_ACTIONS.get(action)
        if not meta:
            continue
        try:
            outcome, staged = await _call_action(meta["stage"], SYSTEM_CONTEXT, p["client_id"], p.get("args") or {})
        except Exception as exc:
            logger.warning("chase_plan_stage_failed", extra={"action": action, "error": str(exc)})
            continue
        if outcome == "reply":
            # Unstageable (ambiguous target / held placement / guard) → flag line.
            flags.append(f"{p.get('reason')} — {staged}")
            continue
        staged.pop("_confirm", None)
        staged.pop("_requester", None)
        if autonomy.get(p.get("kind")) == "auto":
            # Future graduation path (all-propose in v1.4): execute now, report done.
            try:
                result = await _call_action(meta["run"], SYSTEM_CONTEXT, p["client_id"], staged)
                auto_results.append(str(result))
            except Exception as exc:
                flags.append(f"{p.get('reason')} — auto-execution failed ({str(exc)[:80]})")
            continue
        items.append({
            "index": len(items) + 1,
            "action": action,
            "client_id": p["client_id"],
            "client_name": p.get("client_name") or "client",
            "args": staged,
            "reason": p.get("reason") or PACE_ACTIONS[action]["label"],
            "kind": p.get("kind"),
            "min_role": pace_auth.min_role_for(p.get("perm") or action),
        })
    return {"date": today.isoformat(), "items": items,
            "auto_results": auto_results, "flags": flags, "overflow": overflow}


# ---------------------------------------------------------------------------
# Confirm (called from pace_agent's batch pending branch)
# ---------------------------------------------------------------------------
async def execute_plan_selection(items: list[dict], selection: list[int],
                                 context: ActionContext) -> str:
    """Run the selected plan items the confirmer is authorized for. Returns the
    thread reply summarizing ✅ ran / ⛔ not authorized / ❌ failed."""
    from middleware.auth import role_rank

    if context.is_anonymous:
        return "Link your Slack account first — I can't authorize an anonymous confirm."
    by_index = {it["index"]: it for it in items}
    lines: list[str] = []
    for idx in selection:
        it = by_index.get(idx)
        if not it:
            continue
        if role_rank(context.role) < role_rank(it["min_role"]):
            lines.append(f"⛔ {idx}. {it['reason']} — needs *{it['min_role']}* or higher")
            continue
        try:
            result = await _call_action(PACE_ACTIONS[it["action"]]["run"], context, it["client_id"], it["args"])
            lines.append(f"{result}" if str(result).startswith("✅") else f"✅ {result}")
        except Exception as exc:
            logger.warning("chase_plan_run_failed", extra={"action": it["action"], "error": str(exc)})
            lines.append(f"❌ {idx}. {it['reason']} — failed")
    skipped = len(items) - len(selection)
    if skipped > 0:
        lines.append(f"_({skipped} unselected item{'s' if skipped != 1 else ''} dropped — "
                     f"still-relevant ones return in tomorrow's plan.)_")
    return "\n".join(lines) or "Nothing to run."


# ---------------------------------------------------------------------------
# Daily runner (scheduler; gated)
# ---------------------------------------------------------------------------
_last_plan_key: Optional[tuple] = None  # (channel, ts) of the previous plan's pending


async def run_daily_chase_plan(today: Optional[date] = None) -> dict:
    """Build + post today's Chase Plan. Self-gated; once per day (the in-app
    notification's unique dedupe_key is the arbiter — restart-safe). Supersedes
    yesterday's unconfirmed plan. Best-effort."""
    global _last_plan_key
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return {"posted": False, "reason": "disabled"}
    today = today or date.today()
    try:
        plan = await build_chase_plan(today)
    except Exception as exc:
        logger.warning("chase_plan_build_failed", extra={"error": str(exc)})
        return {"posted": False, "reason": "build_failed"}
    if not (plan["items"] or plan["auto_results"] or plan["flags"]):
        return {"posted": False, "reason": "all_clear"}

    text = render_plan(plan)
    # In-app Tier-0 copy + the once-per-day arbiter. skip_channels stops the
    # dispatcher's own Slack copy — the confirmable post below is the Slack copy.
    nid = notifications.emit(
        client_id=None, kind="pace_chase_plan",
        title=f"PACE chase plan — {len(plan['items'])} proposed action{'s' if len(plan['items']) != 1 else ''}",
        summary=text, severity="info",
        payload={"link": "/tasks", "skip_channels": ["slack"]},
        dedupe_key=f"pace_chase_plan:{plan['date']}",
    )
    if nid is None:  # already posted today (dedupe) or notifications disabled
        return {"posted": False, "reason": "deduped"}

    # Supersede yesterday's unconfirmed plan (never execute late).
    from services import pace_agent
    if _last_plan_key:
        pace_agent._pace_pending.pop(_last_plan_key, None)
        _last_plan_key = None

    if not plan["items"]:
        # Nothing confirmable (auto/flags only) — the in-app copy suffices.
        return {"posted": True, "confirmable": False, "items": 0}

    channel = settings.pace_slack_channel or settings.slack_default_channel
    if not (settings.slack_bot_token and channel):
        logger.info("chase_plan_no_slack", extra={"items": len(plan["items"])})
        return {"posted": True, "confirmable": False, "items": len(plan["items"])}
    try:
        from services.slack_assistant import post_message

        ts = await post_message(channel, text)
    except Exception as exc:
        logger.warning("chase_plan_post_failed", extra={"error": str(exc)})
        return {"posted": True, "confirmable": False, "items": len(plan["items"])}
    if ts:
        pace_agent._pace_pending[(channel, ts)] = {"batch": True, "date": plan["date"],
                                                   "items": plan["items"]}
        _last_plan_key = (channel, ts)
    return {"posted": True, "confirmable": bool(ts), "items": len(plan["items"])}
