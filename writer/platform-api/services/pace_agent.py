"""PACE — the conversational persona + router (Phase 3).

docs/modules/project-manager-agent-plan-v1_0.md §4.1/§4.4. Makes the Phase-2
actions reachable and answers PACE-shaped questions ("what's stuck?", "what
should I work on?", "move X to Ivy").

**Safety model:** this is a *parallel, self-contained* handler, NOT a rewrite of
SerMaStr's `interpret()`/`_pending`. Both entry points (`slack_assistant`
`handle_message`, `assistant_chat` `handle_chat`) call `maybe_handle_*` FIRST,
**gated on `pace_enabled`** (default False → the branch is inert, SerMaStr is
byte-for-byte unchanged). `maybe_handle_*` returns "handled / not handled"; a
non-PACE message falls straight through to the existing SerMaStr flow. This
gives the persona split with **inherent two-way tool isolation** (PACE only ever
sees `PACE_ACTIONS`; SerMaStr never sees PACE writes) and its **own** actor-bound
confirm store — no shared-flow surgery.

Routing order (§4.1): actor → pending confirm (actor-bound) → intent classify →
personal-brief bypass (no client) → client/portfolio → PACE reply/action.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import pace_auth, pm_signals
from services.pace_actions import PACE_ACTIONS
from services.pace_auth import ActionContext

logger = logging.getLogger(__name__)

# In-memory confirm stores (mirror SerMaStr's best-effort _pending). Each entry
# carries the REQUESTER so the confirmation is actor-bound (§3.3).
_pace_pending: dict[tuple, dict] = {}        # slack: keyed (channel, thread_ts)
_pace_web_pending: dict[str, dict] = {}      # web: keyed by an opaque token
_WEB_PENDING_TTL = 900.0
_WEB_PENDING_MAX = 500


# ---------------------------------------------------------------------------
# Pure router (unit-tested)
# ---------------------------------------------------------------------------
# PACE-shaped: about task delivery state / assignment / due dates / "today".
_PACE_RE = re.compile(
    r"\b(task|tasks|assign|reassign|assigned|due date|overdue|stuck|blocked|unblock|"
    r"workload|overloaded|my plate|work on today|to-?do|to do|board|reprioriti|"
    r"nudge|generate (this|the) month|month'?s tasks|behind (on )?(pace|schedule)|checklist)\b",
    re.IGNORECASE,
)
_BRIEF_RE = re.compile(
    r"\b(what('?s| is| are)?\s+(should i|on my plate|my tasks|i work on)|"
    r"my tasks( today)?|what do i (work on|have)( today)?|today'?s tasks)\b",
    re.IGNORECASE,
)


def is_pace_message(text: str) -> bool:
    """True when a message is project-management-shaped (→ PACE handles it)."""
    return bool(text and _PACE_RE.search(text))


def is_personal_brief(text: str) -> bool:
    """True for 'what should I work on today?' — answered from the actor's own
    tasks, bypassing client resolution (§4.4)."""
    return bool(text and _BRIEF_RE.search(text))


# ---------------------------------------------------------------------------
# LLM tool schemas (PACE-only — two-way isolation is inherent)
# ---------------------------------------------------------------------------
_TOOL_PARAMS = {
    "reassign_task": {
        "task_name": {"type": "string", "description": "The task to reassign (part of its name)."},
        "assignee": {"type": "string", "description": "The team member to assign it to."},
    },
    "assign_task": {
        "task_name": {"type": "string", "description": "The unassigned task to auto-place on the best-fit member."},
    },
    "set_task_due": {
        "task_name": {"type": "string", "description": "The task to set a due date on."},
        "due_date": {"type": "string", "description": "Due date, YYYY-MM-DD."},
    },
    "unblock_task": {"task_name": {"type": "string", "description": "The blocked task to unblock."}},
    "generate_client_month": {},
    "generate_pace_report": {},
    "nudge_assignee": {"task_name": {"type": "string", "description": "The task whose assignee to nudge."}},
    "triage_task": {
        "task_name": {"type": "string", "description": "The task to triage (part of its name)."},
        "due_date": {"type": "string", "description": "Due date to set if missing, YYYY-MM-DD."},
        "category": {"type": "string", "description": "Category key to set if missing."},
        "est_hours": {"type": "number", "description": "Estimated hours to set if missing."},
    },
    "run_qa_review": {
        "task_name": {"type": "string", "description": "The task whose deliverable to QA (part of its name)."},
    },
}
_TOOL_REQUIRED = {
    "reassign_task": ["task_name", "assignee"],
    "assign_task": ["task_name"],
    "set_task_due": ["task_name", "due_date"],
    "unblock_task": ["task_name"],
    "generate_client_month": [],
    "generate_pace_report": [],
    "triage_task": ["task_name"],
    "nudge_assignee": ["task_name"],
    "run_qa_review": ["task_name"],
}


def build_pace_tools() -> list[dict]:
    return [
        {
            "name": name,
            "description": meta["label"],
            "input_schema": {
                "type": "object",
                "properties": _TOOL_PARAMS.get(name, {}),
                "required": _TOOL_REQUIRED.get(name, []),
            },
        }
        for name, meta in PACE_ACTIONS.items()
    ]


_PACE_SYSTEM = (
    "You are PACE, the delivery project manager for an SEO agency. You keep client "
    "work moving: you surface what's stuck, overdue, unassigned or behind pace, and "
    "you take small operational actions (reassign, set a due date, unblock, generate "
    "the month, nudge an assignee, run a QA review on a finished deliverable) — "
    "always via the provided tools, never by "
    "pretending. You are NOT the strategist (SerMaStr decides what work to do and "
    "why); if asked a strategy/priority/'what should we change' question, say that's "
    "SerMaStr's call and offer to hand off. Answer delivery questions concisely from "
    "the board digest provided. When the teammate asks you to DO something operational, "
    "call the matching tool with your best-guess arguments — the system resolves the "
    "exact task and asks for confirmation. Be brief and concrete."
)


# ---------------------------------------------------------------------------
# Context (deterministic board digest for the client)
# ---------------------------------------------------------------------------
def build_pace_context(client_id: str) -> dict:
    """The client's PACE board digest — the deterministic signals, as the LLM's
    grounding. No paid calls."""
    try:
        return pm_signals.build_client_signals(client_id)
    except Exception as exc:
        logger.warning("pace_context_failed", extra={"client_id": client_id, "error": str(exc)})
        return {"client_id": client_id, "error": "context_unavailable"}


# ---------------------------------------------------------------------------
# Personal brief (deterministic — the actor's own tasks, no client, no LLM)
# ---------------------------------------------------------------------------
def personal_brief_text(context: ActionContext) -> str:
    """'What should I work on today?' from the actor's linked roster member's My
    Tasks. Deterministic + prioritized (overdue → today → this week). Needs the
    identity bridge; an unlinked actor is told to link."""
    from services import task_service

    if context.is_anonymous:
        return "Link your account first so I know whose tasks to show (an admin can do it on the Team page)."
    gid = None
    rows = (
        get_supabase().table("asana_team_members").select("gid")
        .eq("profile_id", context.profile_id).limit(1).execute()
    ).data
    if rows:
        gid = rows[0]["gid"]
    if not gid:
        return "You're not linked to a task-board member yet — ask an admin to link you on the Team page."
    tasks = (
        get_supabase().table("tasks")
        .select("id, client_id, name, due_date, status_key")
        .eq("assignee_gid", gid).eq("completed", False)
        .is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or []
    if not tasks:
        return "You're all clear — nothing open assigned to you. 🎉"
    buckets = task_service.bucket_by_due(tasks, date.today())
    names = _client_names([t.get("client_id") for t in tasks])
    lines: list[str] = []
    for key, label in (("overdue", "Overdue"), ("today", "Due today"), ("this_week", "This week")):
        rows_b = buckets.get(key) or []
        if rows_b:
            lines.append(f"*{label}:*")
            lines.extend(f"• {t['name']} — {names.get(t.get('client_id'), 'client')}" for t in rows_b[:6])
    if not lines:  # only later/no-date work
        later = (buckets.get("later") or []) + (buckets.get("no_date") or [])
        lines.append("Nothing overdue or due this week. Next up:")
        lines.extend(f"• {t['name']} — {names.get(t.get('client_id'), 'client')}" for t in later[:6])
    return "\n".join(lines)


def _client_names(client_ids: list) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


# ---------------------------------------------------------------------------
# LLM interpret (PACE loop — reuses the shared Anthropic primitive)
# ---------------------------------------------------------------------------
async def interpret_pace(question: str, client: dict, context: dict,
                         history: Optional[list[dict]] = None, style: str = "slack",
                         on_event=None) -> tuple[str, object]:
    """One PACE turn: ("action", {name, args}) when a PACE tool is called, else
    ("text", reply). Reuses `_one_llm_call`; cheap model (`pace_model`)."""
    import json

    import anthropic

    from services.slack_assistant.llm import _one_llm_call, format_history

    blocks = []
    if history:
        blocks.append("Conversation so far:\n" + format_history(history))
    blocks.append(f"Client: {client.get('name')}")
    blocks.append("Board digest (JSON):\n" + json.dumps(context, default=str, ensure_ascii=False))
    blocks.append(f"Latest message: {question}")
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    call_kwargs = {"model": settings.pace_model, "max_tokens": settings.pace_max_tokens}
    try:
        resp = await _one_llm_call(
            api, _PACE_SYSTEM, [{"role": "user", "content": "\n\n".join(blocks)}],
            build_pace_tools(), call_kwargs, on_text if on_event else None,
        )
    except anthropic.APIStatusError as exc:
        if exc.status_code in (429, 529, 503):
            return ("text", "PACE is busy right now — try again in a moment.")
        raise
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name in PACE_ACTIONS:
            return ("action", {"name": b.name, "args": dict(b.input or {})})
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return ("text", "\n".join(parts).strip() or "I couldn't work that out — try rephrasing.")


async def _run_pace_action(name: str, client_id: str, args: dict, context: ActionContext) -> str:
    out = PACE_ACTIONS[name]["run"](context, client_id, args or {})
    if inspect.isawaitable(out):
        out = await out
    return out


# ---------------------------------------------------------------------------
# Slack entry (delegated from handle_message, gated on pace_enabled)
# ---------------------------------------------------------------------------
async def maybe_handle_slack(event: dict, context: ActionContext, *, force: bool = False) -> bool:
    """Handle a Slack message if it's PACE's (a pending PACE confirm, or a
    PACE-shaped message). Returns True when handled → the caller stops; False →
    fall through to SerMaStr. Best-effort.

    ``force=True`` (the dedicated PACE channel, §10.2): PACE owns every message —
    the ``is_pace_message`` gate is skipped, so even a non-delivery ask is
    answered by PACE (its prompt defers strategy to SerMaStr)."""
    from services.slack_assistant import (is_affirmative, post_message,
                                           resolve_client, strip_mention)

    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    question = strip_mention(event.get("text", ""))
    if not (channel and question):
        return False
    pend_key = (channel, thread_ts)

    # 1) Actor-bound confirmation of a staged PACE action.
    pending = _pace_pending.get(pend_key)
    if pending and pending.get("batch"):
        # A Chase Plan thread (§4.8): selective confirm ("yes" / "yes 1,3").
        # Non-approval replies leave the plan pending (it expires only when the
        # next day's plan supersedes it) and fall through to normal handling.
        from services import pace_proposals

        selection = pace_proposals.parse_plan_reply(question, len(pending["items"]))
        if selection is not None:
            _pace_pending.pop(pend_key, None)
            reply = await pace_proposals.execute_plan_selection(pending["items"], selection, context)
            await post_message(channel, reply, thread_ts)
            return True
        pending = None  # not an approval — treat as an ordinary message below
    if pending:
        if is_affirmative(question):
            _pace_pending.pop(pend_key, None)
            if not pace_auth.confirm_actor_ok(pending.get("requester"), context):
                await post_message(channel, "Only the person who requested this can confirm it.", thread_ts)
                return True
            try:
                reply = await _run_pace_action(pending["action"], pending["client_id"], pending["args"], context)
            except Exception as exc:
                logger.warning("pace_action_run_failed", extra={"action": pending["action"], "error": str(exc)})
                reply = "Sorry — that action failed. Try again."
            await post_message(channel, reply, thread_ts)
            return True
        _pace_pending.pop(pend_key, None)  # superseded

    if not force and not is_pace_message(question):
        return False

    try:
        if is_personal_brief(question):
            await post_message(channel, personal_brief_text(context), thread_ts)
            return True
        clients = (get_supabase().table("clients").select("id, name, website_url").execute()).data or []
        client = resolve_client(question, clients)
        if not client:
            await post_message(channel, _portfolio_pace_text(), thread_ts)
            return True
        board = build_pace_context(client["id"])
        kind, payload = await interpret_pace(question, client, board)
        if kind == "action":
            handled_reply = await _stage_or_run_slack(payload, client, context, pend_key)
            await post_message(channel, handled_reply, thread_ts)
            return True
        await post_message(channel, payload, thread_ts)
        return True
    except Exception as exc:
        logger.warning("pace_slack_failed", extra={"channel": channel, "error": str(exc)})
        await post_message(channel, "Sorry — PACE hit an error.", thread_ts)
        return True


async def _stage_or_run_slack(payload: dict, client: dict, context: ActionContext,
                              pend_key: tuple) -> str:
    name, args = payload["name"], payload["args"]
    outcome, staged = await _stage(name, context, client["id"], args)
    if outcome == "reply":
        return staged
    confirm = staged.pop("_confirm", None)
    requester = staged.pop("_requester", None)
    _pace_pending[pend_key] = {"action": name, "client_id": client["id"],
                               "args": staged, "requester": requester}
    return f"This will {confirm} for *{client['name']}*. Reply *yes* to proceed."


async def _stage(name: str, context: ActionContext, client_id: str, args: dict):
    out = PACE_ACTIONS[name]["stage"](context, client_id, args)
    if inspect.isawaitable(out):
        out = await out
    return out


def _portfolio_pace_text() -> str:
    """A deterministic agency-wide delivery read when no client is named."""
    try:
        board = pm_signals.build_board_digest(None)
    except Exception:
        return "Which client's board did you mean?"
    clients = board.get("clients", [])
    behind = [c for c in clients if (c.get("month_pace") or {}).get("behind")]
    stuck = sum(len(c.get("stale", [])) for c in clients)
    overdue = sum(len(c.get("overdue", [])) for c in clients)
    if not (behind or stuck or overdue):
        return "Delivery looks healthy across all boards — nothing stuck, overdue, or behind pace."
    parts = []
    if stuck:
        parts.append(f"{stuck} stuck task{'s' if stuck != 1 else ''}")
    if overdue:
        parts.append(f"{overdue} overdue")
    if behind:
        parts.append(f"{len(behind)} client{'s' if len(behind) != 1 else ''} behind pace")
    return "Across all boards: " + ", ".join(parts) + ". Name a client and I'll break it down."


# ---------------------------------------------------------------------------
# Web entry (delegated from handle_chat, gated on pace_enabled)
# ---------------------------------------------------------------------------
def _store_web_pending(action: str, client: dict, args: dict, requester: Optional[str]) -> str:
    import uuid
    now = time.time()
    for tok, e in list(_pace_web_pending.items()):
        if now - e["created"] > _WEB_PENDING_TTL:
            _pace_web_pending.pop(tok, None)
    while len(_pace_web_pending) >= _WEB_PENDING_MAX:
        _pace_web_pending.pop(min(_pace_web_pending, key=lambda t: _pace_web_pending[t]["created"]), None)
    token = uuid.uuid4().hex
    _pace_web_pending[token] = {"action": action, "client_id": client["id"],
                                "client_name": client.get("name"), "args": args,
                                "requester": requester, "created": now}
    return token


async def maybe_handle_web(message: str, history: list[dict], sticky_client_id: Optional[str],
                           pending_token: Optional[str], context: ActionContext,
                           on_event=None) -> Optional[dict]:
    """Handle a web chat turn if it's PACE's (a PACE pending token, or a
    PACE-shaped message). Returns the chat payload dict when handled, else None
    → fall through to SerMaStr. On web the confirmer is the authenticated
    session, so actor-binding is inherent; we still check it.

    The deterministic reads (client list, board digest, brief/portfolio text)
    do blocking Supabase I/O, so they're pushed to a threadpool to keep the
    request event loop free — matching `assistant_chat.handle_chat`'s convention
    (the Slack path mirrors `handle_message`, which reads synchronously)."""
    from fastapi.concurrency import run_in_threadpool

    from services.slack_assistant import is_affirmative, resolve_client

    # 1) Confirm a staged PACE web action (its own token store).
    if pending_token and pending_token in _pace_web_pending:
        entry = _pace_web_pending.pop(pending_token)
        if is_affirmative(message):
            if not pace_auth.confirm_actor_ok(entry.get("requester"), context):
                return {"reply": "Only the person who requested this can confirm it."}
            try:
                reply = await _run_pace_action(entry["action"], entry["client_id"], entry["args"], context)
            except Exception as exc:
                logger.warning("pace_web_action_failed", extra={"action": entry["action"], "error": str(exc)})
                reply = "Sorry — that action failed."
            return {"reply": reply, "client_id": entry["client_id"], "client_name": entry.get("client_name")}
        # Non-affirmative supersedes; fall through to normal handling.

    if not is_pace_message(message):
        return None
    try:
        if is_personal_brief(message):
            return {"reply": await run_in_threadpool(personal_brief_text, context)}
        clients = await run_in_threadpool(
            lambda: (get_supabase().table("clients").select("id, name").execute()).data or []
        )
        named = resolve_client(message, clients)
        client = named or (next((c for c in clients if c["id"] == sticky_client_id), None) if sticky_client_id else None)
        if not client:
            return {"reply": await run_in_threadpool(_portfolio_pace_text)}
        board = await run_in_threadpool(build_pace_context, client["id"])
        kind, payload = await interpret_pace(message, client, board, history, style="web", on_event=on_event)
        base = {"client_id": client["id"], "client_name": client.get("name")}
        if kind == "action":
            name, args = payload["name"], payload["args"]
            outcome, staged = await _stage(name, context, client["id"], args)
            if outcome == "reply":
                return {**base, "reply": staged}
            confirm = staged.pop("_confirm", None)
            requester = staged.pop("_requester", None)
            token = _store_web_pending(name, client, staged, requester)
            return {**base, "reply": f"This will {confirm} for **{client['name']}**. Confirm to proceed.",
                    "pending_token": token}
        return {**base, "reply": payload}
    except Exception as exc:
        logger.warning("pace_web_failed", extra={"error": str(exc)})
        return {"reply": "Sorry — PACE hit an error."}
