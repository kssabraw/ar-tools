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
    "You are PACE, the delivery project manager for an SEO agency. Answer like a "
    "sharp, proactive PM who actually knows the board — not a dashboard that quotes "
    "totals.\n\n"
    "ALWAYS ENUMERATE. When asked what is overdue / stuck / blocked / unassigned / "
    "on someone's plate, LIST THE ACTUAL TASKS from the board data — never answer "
    "with just a count. For each task give the task name, the client, the assignee, "
    "and the due date (or how many days overdue / days stuck in status). Group by "
    "urgency: overdue first, then due soon, then stuck. If the list is long, show "
    "the ~10 most urgent and say how many more remain. Give a bare number only when "
    "the board data genuinely contains no matching rows.\n\n"
    "BE A PM, NOT A REPORT. After you list the problems, say what you'd do about "
    "them and offer to do it — name the specific lever per item (reassign, nudge the "
    "assignee, set or bump a due date, unblock, triage, generate the month, run a QA "
    "review). Take initiative: propose the next action. Example: \"Ivy has 3 overdue "
    "— the GBP audit is 6 days late; want me to nudge her or bump the date?\"\n\n"
    "ACTIONS. When the teammate asks you to DO something operational, call the "
    "matching tool with your best-guess arguments — the system resolves the exact "
    "task/member and asks for a confirmation. Don't ask permission before calling "
    "the tool; the confirm step IS the permission, so offer and act freely.\n\n"
    "SCOPE. The board data you're given is either one client, one team member across "
    "ALL their clients, or the whole agency (every board). Answer within that scope "
    "and name clients and people explicitly.\n\n"
    "NOT THE STRATEGIST. SerMaStr decides what work to do and why. If asked a "
    "strategy / priority / 'what should we change' question, say that's SerMaStr's "
    "call and offer to hand it off — but delivery status, who's behind, and what's "
    "late are yours to answer in full.\n\n"
    "GROUNDING. Only state tasks, assignees, and statuses that appear in the board "
    "data. Be concrete and specific; skip filler."
)


# ---------------------------------------------------------------------------
# Context (deterministic board digest for the client)
# ---------------------------------------------------------------------------
def build_pace_context(client_id: str) -> dict:
    """The client's PACE board digest — the deterministic signals, as the LLM's
    grounding. No paid calls."""
    try:
        signals = pm_signals.build_client_signals(client_id)
    except Exception as exc:
        logger.warning("pace_context_failed", extra={"client_id": client_id, "error": str(exc)})
        return {"client_id": client_id, "error": "context_unavailable"}
    # Attach the roster so the LLM can enumerate assignees and offer per-owner
    # actions without a second read.
    signals["team_members"] = [m.get("name") for m in _active_members() if m.get("name")]
    return signals


# Actions that name a whole client rather than a single task — they can't be
# resolved from a task name in member/portfolio scope, so they need a named client.
_TASKLESS_ACTIONS = {"generate_client_month", "generate_pace_report"}
# How many rows per bucket to hand the LLM (keeps the portfolio JSON bounded on a
# big agency; the prompt still says "and N more").
_PORTFOLIO_ROW_CAP = 12


def _all_clients() -> list[dict]:
    return (get_supabase().table("clients").select("id, name, website_url").execute()).data or []


def _active_members() -> list[dict]:
    return (
        get_supabase().table("asana_team_members")
        .select("gid, name, profile_id").eq("active", True).execute()
    ).data or []


def resolve_member(text: str, members: list[dict]) -> Optional[dict]:
    """The roster member named in ``text`` (full name or first name, whole-word,
    longest match wins), or None. Powers the per-staff-member scope
    ("what does Ivy have overdue?"). Pure."""
    if not text:
        return None
    best, best_len = None, 0
    for m in members:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        for cand in {name.lower(), name.split()[0].lower()}:
            if len(cand) < 3:
                continue
            if re.search(rf"\b{re.escape(cand)}\b", text, re.IGNORECASE) and len(cand) > best_len:
                best, best_len = m, len(cand)
    return best


def build_member_context(member: dict, today: Optional[date] = None) -> dict:
    """One team member's open tasks across ALL clients, bucketed by urgency, with
    client names attached — the deterministic grounding for a per-member question.
    No paid calls."""
    from services import task_service

    today = today or date.today()
    gid = member.get("gid")
    tasks = (
        get_supabase().table("tasks")
        .select("id, client_id, name, due_date, status_key, category, created_at")
        .eq("assignee_gid", gid).eq("completed", False)
        .is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or [] if gid else []
    names = _client_names([t.get("client_id") for t in tasks])

    def _row(t: dict) -> dict:
        return {"id": t["id"], "name": t.get("name"),
                "client": names.get(t.get("client_id"), "unknown"),
                "due_date": t.get("due_date"), "status_key": t.get("status_key")}

    buckets = task_service.bucket_by_due(tasks, today)
    return {
        "member": member.get("name"),
        "open_count": len(tasks),
        "overdue": [_row(t) for t in (buckets.get("overdue") or [])],
        "due_today": [_row(t) for t in (buckets.get("today") or [])],
        "this_week": [_row(t) for t in (buckets.get("this_week") or [])],
        "later": [_row(t) for t in (buckets.get("later") or [])],
        "no_due_date": [_row(t) for t in (buckets.get("no_date") or [])],
    }


def build_portfolio_context(today: Optional[date] = None) -> dict:
    """The whole-agency board digest with client names attached and per-bucket
    lists capped — so the LLM can enumerate what's overdue/stuck across every
    board instead of quoting a total. No paid calls."""
    digest = pm_signals.build_board_digest(None, today)
    clients = digest.get("clients", [])
    names = _client_names([c.get("client_id") for c in clients])
    for c in clients:
        c["client_name"] = names.get(c.get("client_id"), "unknown")
        for key in ("stale", "overdue", "unassigned", "no_due_date", "unacted_producer"):
            rows = c.get(key)
            if isinstance(rows, list) and len(rows) > _PORTFOLIO_ROW_CAP:
                c[key] = rows[:_PORTFOLIO_ROW_CAP] + [{"_truncated": len(rows) - _PORTFOLIO_ROW_CAP}]
    return digest


def _resolve_task_client(task_name: str):
    """In member/portfolio scope an action names a task, not a client — find the
    task across every board and return its client. Returns (client_dict, None) on
    a unique client, or (None, reply) to send back (no match / spans clients)."""
    from services.slack_assistant.actions import match_open_tasks

    query = (task_name or "").strip()
    if not query:
        return None, "Which task? Give me (part of) its name."
    rows = (
        get_supabase().table("tasks")
        .select("id, name, client_id")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .not_.is_("client_id", "null")
        .execute()
    ).data or []
    matches = match_open_tasks(rows, query)
    if not matches:
        return None, f"No open task matches “{query}”."
    client_ids = {m.get("client_id") for m in matches}
    if len(client_ids) > 1:
        names = _client_names(list(client_ids))
        which = ", ".join(sorted(names.get(cid, "unknown") for cid in client_ids))
        return None, f"“{query}” matches tasks on more than one client ({which}) — which client?"
    cid = matches[0]["client_id"]
    return {"id": cid, "name": _client_names([cid]).get(cid, "the client")}, None


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
async def interpret_pace(question: str, client: Optional[dict], context: dict,
                         history: Optional[list[dict]] = None, style: str = "slack",
                         on_event=None, scope: str = "client") -> tuple[str, object]:
    """One PACE turn: ("action", {name, args}) when a PACE tool is called, else
    ("text", reply). Reuses `_one_llm_call`; Sonnet (`pace_model`).

    ``scope`` is ``"client"`` (``client`` set), ``"member"`` (``context['member']``
    across all boards), or ``"portfolio"`` (every board) — it frames the board
    data so the LLM enumerates within the right scope."""
    import json

    import anthropic

    from services.slack_assistant.llm import _one_llm_call, format_history

    blocks = []
    if history:
        blocks.append("Conversation so far:\n" + format_history(history))
    if scope == "member":
        blocks.append(f"Scope: team member *{context.get('member')}* — their open tasks across ALL clients.")
    elif scope == "portfolio":
        blocks.append("Scope: the whole agency — every client board.")
    else:
        blocks.append(f"Scope: the client *{client.get('name') if client else 'this client'}*.")
    blocks.append("Board data (JSON):\n" + json.dumps(context, default=str, ensure_ascii=False))
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
# Shared turn resolution (scope → interpret → stage), used by both entrypoints
# ---------------------------------------------------------------------------
async def _run_direct(fn, *args):
    """Runner shim for the Slack path — its reads are already off the request
    loop, so blocking calls run inline (mirrors the web path's run_in_threadpool)."""
    return fn(*args)


def _fallback_text(scope: str) -> str:
    if scope == "portfolio":
        return _portfolio_pace_text()
    return "Sorry — PACE couldn't pull the board just now. Try again in a moment."


def _resolve_scope(question: str, sticky_client_id: Optional[str]) -> tuple[str, Optional[dict], dict]:
    """Pick the scope for a turn and build its deterministic board data.

    Precedence: an explicitly named client wins (most specific), else a named
    team member → cross-client member scope, else the sticky client, else the
    whole-agency portfolio. Blocking (DB reads) — call via a runner."""
    from services.slack_assistant import resolve_client

    clients = _all_clients()
    named_client = resolve_client(question, clients)
    if named_client:
        return "client", named_client, build_pace_context(named_client["id"])
    member = resolve_member(question, _active_members())
    if member:
        return "member", member, build_member_context(member)
    if sticky_client_id:
        sticky = next((c for c in clients if c["id"] == sticky_client_id), None)
        if sticky:
            return "client", sticky, build_pace_context(sticky["id"])
    return "portfolio", None, build_portfolio_context()


async def _answer(question: str, history: Optional[list[dict]], sticky_client_id: Optional[str],
                  actor: ActionContext, style: str, on_event, runner) -> dict:
    """One PACE turn, entrypoint-neutral. Resolves scope, interprets, and stages
    any action (resolving the target client from the task in member/portfolio
    scope). Returns:
        {"reply": str|None, "client_id"?, "client_name"?,
         "pending": {name, client_id, client_name, args, requester, confirm}?}
    Each entrypoint formats the confirmation + owns its pending store."""
    scope, subject, ctx = await runner(_resolve_scope, question, sticky_client_id)
    client = subject if scope == "client" else None
    base = {"client_id": client["id"], "client_name": client.get("name")} if client else {}

    try:
        kind, payload = await interpret_pace(question, client, ctx, history, style, on_event, scope=scope)
    except Exception as exc:
        logger.warning("pace_interpret_failed", extra={"scope": scope, "error": str(exc)})
        return {**base, "reply": _fallback_text(scope)}
    if kind == "text":
        return {**base, "reply": payload}

    # An action. Resolve the target client — given in client scope, else from the
    # task name across all boards.
    name, args = payload["name"], dict(payload.get("args") or {})
    if client:
        action_client = client
    elif name in _TASKLESS_ACTIONS:
        return {**base, "reply": "Which client's board? Name the client and I'll run that."}
    else:
        action_client, reply = await runner(_resolve_task_client, args.get("task_name", ""))
        if reply:
            return {**base, "reply": reply}

    ac_base = {"client_id": action_client["id"], "client_name": action_client.get("name")}
    outcome, staged = await _stage(name, actor, action_client["id"], args)
    if outcome == "reply":
        return {**ac_base, "reply": staged}
    confirm = staged.pop("_confirm", None)
    requester = staged.pop("_requester", None)
    return {**ac_base, "reply": None,
            "pending": {"name": name, "client_id": action_client["id"],
                        "client_name": action_client.get("name"), "args": staged,
                        "requester": requester, "confirm": confirm}}


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
                                           strip_mention)

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
        result = await _answer(question, None, None, context, "slack", None, _run_direct)
        pending = result.get("pending")
        if pending:
            _pace_pending[pend_key] = {"action": pending["name"], "client_id": pending["client_id"],
                                       "args": pending["args"], "requester": pending["requester"]}
            await post_message(
                channel,
                f"This will {pending['confirm']} for *{pending['client_name']}*. Reply *yes* to proceed.",
                thread_ts,
            )
            return True
        await post_message(channel, result.get("reply") or "I couldn't work that out — try rephrasing.", thread_ts)
        return True
    except Exception as exc:
        logger.warning("pace_slack_failed", extra={"channel": channel, "error": str(exc)})
        await post_message(channel, "Sorry — PACE hit an error.", thread_ts)
        return True


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
                           on_event=None, force: bool = False) -> Optional[dict]:
    """Handle a web chat turn if it's PACE's (a PACE pending token, or a
    PACE-shaped message). Returns the chat payload dict when handled, else None
    → fall through to SerMaStr. On web the confirmer is the authenticated
    session, so actor-binding is inherent; we still check it.

    `force=True` is the **dedicated PACE surface** path (the /pace sidebar chat):
    the shape gate is skipped so PACE answers every turn — the persona defers
    strategy questions to SerMaStr in prose rather than by falling through. With
    `force=True` this never returns None.

    The deterministic reads (client list, board digest, brief/portfolio text)
    do blocking Supabase I/O, so they're pushed to a threadpool to keep the
    request event loop free — matching `assistant_chat.handle_chat`'s convention
    (the Slack path mirrors `handle_message`, which reads synchronously)."""
    from fastapi.concurrency import run_in_threadpool

    from services.slack_assistant import is_affirmative

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

    if not force and not is_pace_message(message):
        return None
    try:
        if is_personal_brief(message):
            return {"reply": await run_in_threadpool(personal_brief_text, context)}
        result = await _answer(message, history, sticky_client_id, context, "web", on_event, run_in_threadpool)
        pending = result.get("pending")
        if pending:
            token = _store_web_pending(
                pending["name"], {"id": pending["client_id"], "name": pending["client_name"]},
                pending["args"], pending["requester"],
            )
            return {"client_id": pending["client_id"], "client_name": pending["client_name"],
                    "reply": f"This will {pending['confirm']} for **{pending['client_name']}**. Confirm to proceed.",
                    "pending_token": token}
        out = {"reply": result.get("reply") or "I couldn't work that out — try rephrasing."}
        if result.get("client_id"):
            out["client_id"] = result["client_id"]
            out["client_name"] = result.get("client_name")
        return out
    except Exception as exc:
        logger.warning("pace_web_failed", extra={"error": str(exc)})
        return {"reply": "Sorry — PACE hit an error."}
