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
from services import notifications, pace_auth, pace_batch, pace_interventions, pm_signals
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
    r"nudge|generate (this|the) month|month'?s tasks|behind (on )?(pace|schedule)|checklist|"
    r"client pulse|weekly pulse|client update|reopen|in qa|sent to client|client approved|"
    r"mark .{0,60}(completed?|done))\b",
    re.IGNORECASE,
)
_BRIEF_RE = re.compile(
    r"\b(what('?s| is| are)?\s+(should i|on my plate|my tasks|i work on)|"
    r"my tasks( today)?|what do i (work on|have)( today)?|today'?s tasks)\b",
    re.IGNORECASE,
)


def is_pace_message(text: str) -> bool:
    """True when a message is project-management-shaped (→ PACE handles it)."""
    if not text:
        return False
    # An intervention disposition ("approve 2" / "defer 3 to …") is PACE's too,
    # so the shared-bot path routes it (the dedicated-app path is mention-gated).
    if pace_interventions.parse_intervention_reply(text):
        return True
    return bool(_PACE_RE.search(text))


def is_personal_brief(text: str) -> bool:
    """True for 'what should I work on today?' — answered from the actor's own
    tasks, bypassing client resolution (§4.4)."""
    return bool(text and _BRIEF_RE.search(text))


# An EXPLICIT rejection of a pending confirm ("no", "cancel", "stop", "don't")
# — distinct from merely pivoting to another question, which also supersedes the
# pending but is not a decision to log as a decline. Pure.
_DECLINE_RE = re.compile(
    r"^\s*(no|nope|nah|n|cancel|stop|don'?t|do not|never ?mind|skip|forget it|"
    r"abort|drop it|leave it)\b",
    re.IGNORECASE,
)


def is_explicit_decline(text: str) -> bool:
    """Whether a reply explicitly rejects the pending action (vs. just moving on)."""
    return bool(text and _DECLINE_RE.match(text.strip()))


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
    "set_task_status": {
        "task_name": {"type": "string", "description": "The task to move (part of its name)."},
        "status": {"type": "string", "description": "The workflow status to move it to — e.g. 'In Progress', 'In QA', 'Sent to Client', 'Blocked', 'Completed'. Works forward (work advanced) or backward (needs rework / moved too far)."},
    },
    "unblock_task": {"task_name": {"type": "string", "description": "The blocked task to unblock."}},
    "write_client_pulse": {},
    "generate_client_month": {},
    "generate_pace_report": {},
    "nudge_assignee": {"task_name": {"type": "string", "description": "The task whose assignee to nudge."}},
    "triage_task": {
        "task_name": {"type": "string", "description": "The task to triage (part of its name)."},
        "due_date": {"type": "string", "description": "Due date to set if missing, YYYY-MM-DD."},
        "category": {"type": "string", "description": "Category key to set if missing."},
        "est_hours": {"type": "number", "description": "Estimated hours to set if missing."},
    },
    "rename_task": {
        "task_name": {"type": "string", "description": "The task to rename (part of its current name)."},
        "new_name": {"type": "string", "description": "The new task name."},
    },
    "run_qa_review": {
        "task_name": {"type": "string", "description": "The task whose deliverable to QA (part of its name)."},
    },
    "assign_client_plan": {
        "scope": {"type": "string", "description": "Which plan to put on the board and assign: 'action_plan' (the ranked Action Plan), 'proposals' (the open strategist-review proposals), or 'both' (default)."},
    },
}
_TOOL_REQUIRED = {
    "reassign_task": ["task_name", "assignee"],
    "assign_task": ["task_name"],
    "set_task_due": ["task_name", "due_date"],
    "set_task_status": ["task_name", "status"],
    "unblock_task": ["task_name"],
    "write_client_pulse": [],
    "generate_client_month": [],
    "generate_pace_report": [],
    "triage_task": ["task_name"],
    "rename_task": ["task_name", "new_name"],
    "nudge_assignee": ["task_name"],
    "run_qa_review": ["task_name"],
    "assign_client_plan": [],
}


# Read-only self-history tool: PACE reads its OWN action ledger to answer
# questions about past actions and its approve/deny/modify track record (the
# "learn/teach itself" surface). Executed inline like drill_task — never a write,
# so it's not in PACE_ACTIONS and is never itself logged.
HISTORY_TOOL = {
    "name": "pace_history",
    "description": (
        "Read PACE's OWN recent action log — what PACE changed on client "
        "campaigns and how humans dispositioned each one (approved / "
        "approved-with-modifications / denied / deferred / cancelled). Use it to "
        "answer questions about past PACE actions, what got reverted or declined, "
        "or how often a kind of change is approved vs denied. Read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "client": {"type": "string", "description": "Limit to one client by name; omit for agency-wide."},
            "action": {"type": "string", "description": "Limit to one action type, e.g. reassign_task, set_task_status, intervention_disposition."},
        },
    },
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
    "assignee, set or bump a due date, unblock, triage, move it forward or back "
    "through the workflow, generate the month, run a QA review). Take initiative: "
    "propose the next action. Example: \"Ivy has 3 overdue — the GBP audit is 6 days "
    "late; want me to nudge her or bump the date?\"\n\n"
    "WORKFLOW MOVES. You can move a task through the delivery workflow in EITHER "
    "direction with set_task_status — forward when work advances (→ In QA, Sent to "
    "Client, Client Approved, Completed) and BACK when it needs rework or was moved "
    "too far (→ In Progress, In Review). Marking a task Completed and reopening a "
    "finished one are just status moves.\n\n"
    "CLIENT PULSE. When someone asks for the weekly client update / pulse / \"what do "
    "we tell the client\" / a summary to send the client, call write_client_pulse — "
    "it generates a warm, copy-paste client update email for that client (staff paste "
    "and personalize it; nothing is auto-sent).\n\n"
    "PUT A PLAN ON THE BOARD. When someone asks to take a client's plan / Action Plan "
    "/ approved strategist proposals and get it onto the board and assigned out, call "
    "assign_client_plan (scope 'action_plan', 'proposals', or 'both') — it creates a "
    "board task per item and assigns each to the best-fit member (held if the team's "
    "at capacity). This is the SerMaStr→PACE handoff from your side; it's a PACE PM "
    "action.\n\n"
    "ACTIONS. When the teammate asks you to DO something operational, call the "
    "matching tool with your best-guess arguments — the system resolves the exact "
    "task/member and asks for a confirmation. Don't ask permission before calling "
    "the tool; the confirm step IS the permission, so offer and act freely. To run "
    "one action over a SET of tasks (\"nudge all her overdue\", \"bump every overdue "
    "date\", \"reassign the unassigned ones to Marcus\"), call `batch_action` once "
    "— never fire the same per-task tool many times. To explain WHY a task is stuck "
    "or late, call the read-only `drill_task` first and answer from what it returns "
    "(subtasks, activity, comments, days stuck).\n\n"
    "YOUR OWN TRACK RECORD. Every action you take on a client campaign — and how a "
    "human dispositioned it (approved / approved-with-modifications / denied / "
    "deferred / cancelled) — is logged. When asked what you changed, what got "
    "reverted or declined, or how often a kind of change gets approved, call the "
    "read-only `pace_history` tool and answer from it. Learn from it: if humans "
    "routinely deny or modify a kind of action, say so and adjust what you "
    "propose.\n\n"
    "SCOPE. The board data you're given is either one client, one team member across "
    "ALL their clients, or the whole agency (every board). Answer within that scope "
    "and name clients and people explicitly.\n\n"
    "NOT THE STRATEGIST. SerMaStr decides what work to do and why. If asked a "
    "strategy / priority / 'what should we change' question, say that's SerMaStr's "
    "call and offer to hand it off — but delivery status, who's behind, and what's "
    "late are yours to answer in full.\n\n"
    "GROUNDING. Only state tasks, assignees, and statuses that appear in the board "
    "data. Be concrete and specific; skip filler.\n\n"
    "FORMATTING: you are replying in Slack, which does NOT render standard "
    "Markdown. Never use **bold**, # headers, or [text](url) links — Slack "
    "ignores or mangles them. Use Slack's own mrkdwn instead: *bold* (single "
    "asterisks), _italic_, `code`, bullet lines starting with \"- \" or \"• \", "
    "and <https://example.com|link text> for links. NEVER use a Markdown pipe "
    "table (| Task | Due |...) or a --- horizontal rule — Slack renders neither; "
    "a table shows up as a wall of literal pipe characters. For a task list, use "
    "one bullet per task instead, bolding the task name and folding the rest "
    "inline: \"*Task name* — assignee, due date, N days overdue\". Keep replies "
    "short and scannable — a few lines or a tight list, not walls of text."
)

# Appended instead of the Slack formatting rule above when PACE is answering in
# the dashboard chat (routers/pace.py `style="web"`) rather than Slack — same
# brain, different room. Mirrors slack_assistant/prompts.py's _WEB_STYLE.
_PACE_WEB_STYLE = (
    "\n\nFORMATTING OVERRIDE: you are answering in the AR Tools dashboard chat "
    "(a web app), NOT Slack. Ignore the Slack mrkdwn rule above — format with "
    "standard Markdown instead (**bold**, `-` bullets, [text](url) links), and "
    "never mention Slack, threads, or channels."
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
    # A compact awareness of PACE's own recent track record on this client (counts
    # only — the pace_history tool is the deep read). Best-effort.
    try:
        from services import pace_audit

        # Counts only (no actor names needed) → skip the profiles join: one
        # indexed read per turn, not two.
        summary = pace_audit.history_summary(client_id=client_id, attach_names=False)
        if summary.get("count"):
            signals["pace_action_history"] = {"count": summary["count"],
                                              "decisions": summary["stats"]["overall"]}
    except Exception:
        pass
    return signals


# Actions that name a whole client rather than a single task — they can't be
# resolved from a task name in member/portfolio scope, so they need a named client.
_TASKLESS_ACTIONS = {"generate_client_month", "generate_pace_report", "write_client_pulse",
                     "assign_client_plan"}
# How many rows per bucket to hand the LLM (keeps the portfolio JSON bounded on a
# big agency; the prompt still says "and N more").
_PORTFOLIO_ROW_CAP = 12


def _all_clients() -> list[dict]:
    return (get_supabase().table("clients").select("id, name, website_url").execute()).data or []


def _active_members() -> list[dict]:
    return (
        get_supabase().table("asana_team_members")
        .select("id, gid, name, profile_id").eq("active", True).execute()
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
    member_id = member.get("id")
    tasks = (
        get_supabase().table("tasks")
        .select("id, client_id, name, due_date, status_key, category, created_at")
        .eq("assignee_id", member_id).eq("completed", False)
        .is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or [] if member_id else []
    names = _client_names([t.get("client_id") for t in tasks])

    def _row(t: dict) -> dict:
        return {"id": t["id"], "name": t.get("name"),
                "client_id": t.get("client_id"),
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
    member_id = None
    rows = (
        get_supabase().table("asana_team_members").select("id")
        .eq("profile_id", context.profile_id).limit(1).execute()
    ).data
    if rows:
        member_id = rows[0]["id"]
    if not member_id:
        return "You're not linked to a task-board member yet — ask an admin to link you on the Team page."
    tasks = (
        get_supabase().table("tasks")
        .select("id, client_id, name, due_date, status_key")
        .eq("assignee_id", member_id).eq("completed", False)
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
# Bounded drill-down rounds — PACE may read a couple of stuck tasks in depth
# before answering, then is forced to text.
_PACE_TOOL_ROUNDS = 3


async def interpret_pace(question: str, client: Optional[dict], context: dict,
                         history: Optional[list[dict]] = None, style: str = "slack",
                         on_event=None, scope: str = "client") -> tuple[str, object]:
    """One PACE turn over a bounded tool loop: returns ("action", {name, args})
    for a single PACE_ACTIONS call, ("batch", {action, selector, …}) for a
    `batch_action` call, else ("text", reply). The read-only `drill_task` tool is
    executed inline and folded back so PACE can explain *why* a task is stuck.
    Sonnet (`pace_model`).

    ``scope`` is ``"client"`` (``client`` set), ``"member"`` (``context['member']``
    across all boards), or ``"portfolio"`` (every board) — it frames the board
    data so the LLM enumerates within the right scope."""
    import asyncio
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
    from services import anthropic_failover, prompt_cache

    clients = anthropic_failover.build_async_clients(timeout=60.0, max_retries=2)
    drill_client_id = client.get("id") if client else None
    tools = build_pace_tools() + [pace_batch.DRILL_TOOL, pace_batch.BATCH_TOOL, HISTORY_TOOL]
    # The board-data context is re-sent on every drill-down round; cache it so
    # rounds 2..N read it from cache rather than re-billing the full JSON.
    messages = [{"role": "user", "content": prompt_cache.cache_text("\n\n".join(blocks))}]

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    def _kw(final: bool) -> dict:
        kw = {"model": settings.pace_model, "max_tokens": settings.pace_max_tokens}
        if final:
            kw["tool_choice"] = {"type": "none"}
        return kw

    system = _PACE_SYSTEM + (_PACE_WEB_STYLE if style == "web" else "")

    resp = None
    try:
        for round_no in range(_PACE_TOOL_ROUNDS):
            final = round_no == _PACE_TOOL_ROUNDS - 1
            resp = await anthropic_failover.call_failover(
                clients,
                lambda c: _one_llm_call(
                    c, system, messages, [] if final else tools,
                    _kw(final), on_text if on_event else None,
                ),
                log_tag="pace_agent",
            )
            for b in resp.content:
                if getattr(b, "type", None) != "tool_use":
                    continue
                if b.name in PACE_ACTIONS:
                    return ("action", {"name": b.name, "args": dict(b.input or {})})
                if b.name == pace_batch.BATCH_TOOL["name"]:
                    return ("batch", dict(b.input or {}))
            reads = [b for b in resp.content
                     if getattr(b, "type", None) == "tool_use"
                     and b.name in (pace_batch.DRILL_TOOL["name"], HISTORY_TOOL["name"])]
            if not reads or final:
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in reads:
                inp = dict(b.input or {})
                if b.name == HISTORY_TOOL["name"]:
                    if on_event:
                        await on_event({"type": "status", "label": "Reading PACE action history"})
                    text = await asyncio.to_thread(_history_read, drill_client_id,
                                                   inp.get("client"), inp.get("action"))
                else:
                    name = inp.get("task_name", "")
                    if on_event:
                        await on_event({"type": "status", "label": f"Reading task: {name}".strip()})
                    text = await asyncio.to_thread(_drill_read, name, drill_client_id)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": text})
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as exc:
        if exc.status_code in (429, 529, 503):
            return ("text", "PACE is busy right now — try again in a moment.")
        raise

    parts = [b.text for b in (resp.content if resp else []) if getattr(b, "type", None) == "text"]
    reply = "\n".join(parts).strip() or "I couldn't work that out — try rephrasing."
    if resp is not None and getattr(resp, "stop_reason", None) == "max_tokens":
        # Ran out of room — close cleanly instead of stopping mid-sentence, same
        # pattern as slack_assistant.llm.interpret/interpret_portfolio.
        reply += "\n\n_…I hit my reply-length limit — say “continue” and I'll pick up where I left off._"
    return ("text", reply)


def _drill_read(task_name: str, client_id_hint: Optional[str] = None) -> str:
    """Impure single-task read for the `drill_task` tool — resolve the task
    (within a client hint when in client scope, else across all boards) and
    format its detail. Best-effort; returns a clarification string on miss."""
    from services import task_collab, task_service
    from services.slack_assistant.actions import match_open_tasks

    q = (get_supabase().table("tasks").select("id, name, client_id")
         .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
         .not_.is_("client_id", "null"))
    if client_id_hint:
        q = q.eq("client_id", client_id_hint)
    matches = match_open_tasks(q.execute().data or [], task_name or "")
    if not matches:
        return f"No open task matches “{task_name}”."
    if len({m.get("client_id") for m in matches}) > 1:
        return f"“{task_name}” matches tasks on more than one client — name the client."
    detail = task_service.get_task_detail(matches[0]["id"])
    if not detail:
        return f"“{task_name}” not found."
    days = pm_signals.days_in_status(detail, detail.get("activity") or [], date.today())
    try:
        comments = task_collab.list_comments(matches[0]["id"])
    except Exception:
        comments = []
    return pace_batch.format_drill(detail, comments, days)


def _history_read(client_id_hint: Optional[str], client_name_query: Optional[str],
                  action: Optional[str] = None) -> str:
    """Impure read for the `pace_history` tool — PACE's own recent action ledger +
    a decision-rate rollup, formatted for the LLM. Scope: a named client
    (resolved), else the client in scope, else agency-wide. Best-effort."""
    from services import pace_audit

    client_id = client_id_hint
    if client_name_query:
        from services.slack_assistant import resolve_client

        c = resolve_client(client_name_query, _all_clients())
        # Named a client → scope to it; named something that isn't a client
        # ("all", "everyone") → agency-wide.
        client_id = c["id"] if c else None
    summary = pace_audit.history_summary(client_id=client_id)
    rows = summary["recent"]
    if action:
        rows = [r for r in rows if r.get("action") == action]
    if not rows:
        return "No PACE actions on record for this scope yet."
    ov = summary["stats"]["overall"]
    header = (f"PACE action history ({summary['count']} recent): "
              f"{ov['executed']} executed, {ov['approved']} approved, "
              f"{ov['approved_with_modifications']} approved-with-mods, "
              f"{ov['denied'] + ov['cancelled']} declined, {ov['deferred']} deferred, "
              f"{ov['reverted']} reverted (undone by a human), {ov['failed']} failed.")
    return header + "\n" + pace_audit.format_history(rows)


# How many tasks a single on-demand batch stages (the rest are held).
_BATCH_MAX = 15


async def _stage_batch(action: str, targets: list[dict], extra_args: dict,
                       requester: ActionContext) -> tuple[list[dict], list[str]]:
    """Stage each target as a `PACE_ACTIONS` item under the requester (so each is
    permission-checked and confirm-line'd at stage). Returns (items, flags) —
    items reuse the Chase Plan item shape so `execute_plan_selection` runs them
    verbatim; ``min_role`` is None (already authorized here) so the confirmer
    check is skipped. Unstageable targets become ⚠️ flag lines."""
    items, flags = [], []
    for t in targets:
        args = {"task_name": t["task_name"], **{k: v for k, v in extra_args.items() if v}}
        try:
            outcome, staged = await _stage(action, requester, t["client_id"], args)
        except Exception as exc:
            logger.warning("pace_batch_stage_failed", extra={"action": action, "error": str(exc)})
            flags.append(f"“{t['task_name']}” — couldn't stage")
            continue
        if outcome == "reply":
            flags.append(f"“{t['task_name']}” — {staged}")
            continue
        confirm = staged.pop("_confirm", None)
        staged.pop("_requester", None)
        items.append({"index": len(items) + 1, "action": action, "client_id": t["client_id"],
                      "client_name": t.get("client_name") or "client", "args": staged,
                      "reason": confirm or PACE_ACTIONS[action]["label"], "min_role": None})
    return items, flags


def _log_declined(pending: dict, context: ActionContext) -> None:
    """A staged single action a human replied to with something other than *yes*
    — record it as a cancelled decision (the "human declined PACE's proposal"
    training signal). Best-effort; only logged actions produce a row."""
    from services import pace_audit

    args = pending.get("args") or {}
    tgt = pace_audit.target_from_args(pending.get("action") or "", args)
    pace_audit.record_decision(
        action=pending.get("action") or "", origin="conversational",
        decision="cancelled", outcome="cancelled", context=context,
        client_id=pending.get("client_id"), client_name=pending.get("client_name"),
        reason=pending.get("confirm"), args=args,
        requester=pending.get("requester"), **tgt)


async def _run_pace_action(name: str, client_id: str, args: dict, context: ActionContext,
                           *, origin: str = "conversational", reason: Optional[str] = None,
                           requester: Optional[str] = None,
                           client_name: Optional[str] = None) -> str:
    """Execute a confirmed PACE action, logging it to the action ledger when it's
    campaign-affecting (run_and_log is a no-op logger for reads). Best-effort
    logging never changes the run's result or its exceptions."""
    from services import pace_audit

    return await pace_audit.run_and_log(
        lambda: PACE_ACTIONS[name]["run"](context, client_id, args or {}),
        action=name, context=context, client_id=client_id, args=args or {},
        origin=origin, decision="approved", reason=reason, requester=requester,
        client_name=client_name,
    )


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
    Each entrypoint formats the confirmation + owns its pending store. A
    `batch_action` returns a ``{"batch": {items, flags, overflow, requester}}``
    descriptor instead of ``pending`` — one confirm over many staged items."""
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
    if kind == "batch":
        return await _build_batch(payload, scope, subject, ctx, actor, base)

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


async def _build_batch(payload: dict, scope: str, subject: Optional[dict], ctx: dict,
                       actor: ActionContext, base: dict) -> dict:
    """Expand a `batch_action` call into staged items over the scope's board data.
    Returns a ``{"batch": {...}}`` descriptor the entrypoint turns into one
    confirm, or a plain ``reply`` when nothing was targetable."""
    action = payload.get("action")
    selector = payload.get("selector")
    if action not in pace_batch.BATCH_ACTIONS or not selector:
        return {**base, "reply": "I can batch nudge / reassign / set-due / unblock / triage over "
                                 "overdue / stuck / unassigned / no-due-date tasks — tell me which."}
    targets, overflow = pace_batch.select_targets(scope, subject, ctx, selector, cap=_BATCH_MAX)
    if not targets:
        return {**base, "reply": f"No {selector.replace('_', ' ')} tasks in this scope to act on."}
    extra = {}
    if action == "reassign_task":
        extra = {"assignee": payload.get("assignee") or ""}
    elif action == "set_task_due":
        extra = {"due_date": payload.get("due_date") or ""}
    items, flags = await _stage_batch(action, targets, extra, actor)
    if not items:
        note = (" — " + "; ".join(flags)) if flags else ""
        return {**base, "reply": f"Nothing I could stage for that batch{note}."}
    return {**base, "batch": {"items": items, "flags": flags, "overflow": overflow,
                              "requester": actor.profile_id}}


# ---------------------------------------------------------------------------
# Slack entry (delegated from handle_message, gated on pace_enabled)
# ---------------------------------------------------------------------------
async def maybe_handle_slack(event: dict, context: ActionContext, *, force: bool = False,
                              bot_user_id: Optional[str] = None) -> bool:
    """Handle a Slack message if it's PACE's (a pending PACE confirm, or a
    PACE-shaped message). Returns True when handled → the caller stops; False →
    fall through to SerMaStr. Best-effort.

    ``force=True`` (the dedicated PACE channel, §10.2): PACE owns the channel,
    but — owner ruling 2026-08-29 — only answers a NEW question when
    @-mentioned (``mentions_bot``); the ``is_pace_message`` shape gate stays
    skipped (an @-mentioned message is answered whatever it's shaped like).
    A reply to an already-pending PACE confirmation ("yes", a Chase Plan
    selection) is handled above regardless of mention — the bot is plainly
    the one being replied to, and re-tagging it every turn would be annoying.
    ``bot_user_id`` is PACE's own Slack user id (from the Events API
    envelope's ``authorizations[0].user_id``); pass ``None`` when unknown —
    ``mentions_bot`` degrades to "any mention" rather than going silent."""
    from services.slack_assistant import (is_affirmative, mentions_bot,
                                           post_message as _send, strip_mention)

    # PACE replies post under the PACE app's bot token when a separate app is
    # configured (else the shared token) — so its answers carry the PACE identity.
    _bot_token = notifications.pace_bot_token()

    async def _post(_ch, _text, _thread=None):
        return await _send(_ch, _text, _thread, token=_bot_token)

    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    question = strip_mention(event.get("text", ""))
    if not (channel and question):
        return False
    pend_key = (channel, thread_ts)

    # 1) Actor-bound confirmation of a staged PACE action.
    pending = _pace_pending.get(pend_key)
    if pending and pending.get("intervention"):
        # A staged intervention approval (its plan was previewed) awaiting *yes*.
        if is_affirmative(question):
            _pace_pending.pop(pend_key, None)
            if not pace_auth.confirm_actor_ok(pending.get("requester"), context):
                await _post(channel, "Only the person who requested this can confirm it.", thread_ts)
                return True
            try:
                reply = await pace_interventions.run_pending_disposition(pending, context)
            except Exception as exc:
                logger.warning("pace_intervention_run_failed", extra={"error": str(exc)})
                reply = "Sorry — running that intervention failed."
            await _post(channel, reply, thread_ts)
            return True
        _pace_pending.pop(pend_key, None)  # not a yes → cancelled; fall through
        pending = None
    if pending and pending.get("batch"):
        # A Chase Plan thread (§4.8): selective confirm ("yes" / "yes 1,3").
        # Non-approval replies leave the plan pending (it expires only when the
        # next day's plan supersedes it) and fall through to normal handling.
        from services import pace_proposals

        selection = pace_proposals.parse_plan_reply(question, len(pending["items"]))
        if selection is not None:
            _pace_pending.pop(pend_key, None)
            if pending.get("requester"):
                # On-demand batch → actor-bound (only the staff member who staged
                # it may confirm; an admin may take over).
                if not pace_auth.confirm_actor_ok(pending["requester"], context):
                    await _post(channel, "Only the person who requested this can confirm it.", thread_ts)
                    return True
            else:
                # The scheduled daily Chase Plan → only a PACE PM may approve it
                # (owner ruling 2026-09-01: Minda / Kyle / Ryan, not any staff).
                # Per-item role checks in execute_plan_selection still apply.
                if not pace_auth.is_pace_pm(context):
                    await _post(channel, "Only a PACE PM can approve the daily plan.", thread_ts)
                    return True
            reply = await pace_proposals.execute_plan_selection(
                pending["items"], selection, context,
                origin="batch" if pending.get("on_demand") else "chase_plan",
                chase_plan_date=pending.get("date"))
            await _post(channel, reply, thread_ts)
            return True
        pending = None  # not an approval — treat as an ordinary message below
    if pending:
        if is_affirmative(question):
            _pace_pending.pop(pend_key, None)
            if not pace_auth.confirm_actor_ok(pending.get("requester"), context):
                await _post(channel, "Only the person who requested this can confirm it.", thread_ts)
                return True
            try:
                reply = await _run_pace_action(
                    pending["action"], pending["client_id"], pending["args"], context,
                    reason=pending.get("confirm"), requester=pending.get("requester"),
                    client_name=pending.get("client_name"))
            except Exception as exc:
                logger.warning("pace_action_run_failed", extra={"action": pending["action"], "error": str(exc)})
                reply = "Sorry — that action failed. Try again."
            await _post(channel, reply, thread_ts)
            return True
        if is_explicit_decline(question):  # a real "no" — training signal
            _log_declined(pending, context)
        _pace_pending.pop(pend_key, None)  # superseded (a pivot isn't a decline)

    if force:
        # No pending confirm to continue (handled above) — a fresh question
        # in the dedicated channel needs an explicit @-mention.
        if not mentions_bot(event.get("text", ""), bot_user_id):
            return False
    elif not is_pace_message(question):
        return False

    try:
        # PACE intervention disposition ("approve 2" / "deny 2" / "defer 2 to …" /
        # "approve 2 but only reassign to Ivy"). Falls through when the index isn't
        # a currently-posted intervention (→ normal handling). Approve/conditions
        # PREVIEW the exact plan and require a *yes* to run (a bulk write); deny
        # and defer (safe) execute immediately.
        if pace_interventions.enabled():
            disp = pace_interventions.parse_intervention_reply(question)
            if disp:
                d = disp["disposition"]
                if d in ("approve", "conditions"):
                    iid = pace_interventions.resolve_reference(channel, disp)
                    if iid:
                        prep = await pace_interventions.prepare_slack_approval(
                            iid, d, disp.get("conditions"), context)
                        if prep.get("stage"):
                            _pace_pending[pend_key] = {"intervention": iid, "disposition": d,
                                                       "conditions": disp.get("conditions"),
                                                       "requester": context.profile_id}
                        await _post(channel, prep["text"], thread_ts)
                        return True
                else:  # deny / defer — safe, execute now
                    reply = await pace_interventions.dispose_from_slack(channel, disp, context)
                    if reply is not None:
                        await _post(channel, reply, thread_ts)
                        return True
        if is_personal_brief(question):
            await _post(channel, personal_brief_text(context), thread_ts)
            return True
        result = await _answer(question, None, None, context, "slack", None, _run_direct)
        batch = result.get("batch")
        if batch:
            _pace_pending[pend_key] = {"batch": True, "items": batch["items"],
                                       "requester": batch["requester"], "on_demand": True}
            await _post(
                channel, pace_batch.render_batch(batch["items"], batch["flags"], batch.get("overflow", 0)),
                thread_ts,
            )
            return True
        pending = result.get("pending")
        if pending:
            _pace_pending[pend_key] = {"action": pending["name"], "client_id": pending["client_id"],
                                       "args": pending["args"], "requester": pending["requester"],
                                       "confirm": pending.get("confirm"),
                                       "client_name": pending.get("client_name")}
            await _post(
                channel,
                f"This will {pending['confirm']} for *{pending['client_name']}*. Reply *yes* to proceed.",
                thread_ts,
            )
            return True
        await _post(channel, result.get("reply") or "I couldn't work that out — try rephrasing.", thread_ts)
        return True
    except Exception as exc:
        logger.warning("pace_slack_failed", extra={"channel": channel, "error": str(exc)})
        await _post(channel, "Sorry — PACE hit an error.", thread_ts)
        return True


async def handle_pace_message(event: dict, bot_user_id: Optional[str] = None) -> None:
    """Inbound handler for the dedicated PACE Slack app (``/slack/pace/events``).
    That app lives only in the PACE channel, so every non-bot message there is
    PACE's to answer — resolve the actor and force-handle it (the
    ``is_pace_message`` shape gate is skipped; a fresh question still needs an
    @-mention, see ``maybe_handle_slack``). ``bot_user_id`` is PACE's own Slack
    user id, threaded from the router's Events API payload. Best-effort."""
    try:
        actor = pace_auth.resolve_slack_actor(event.get("user"), event.get("channel"))
        await maybe_handle_slack(event, actor, force=True, bot_user_id=bot_user_id)
    except Exception as exc:  # never surface into the ack path
        logger.warning("pace_inbound_failed",
                       extra={"channel": event.get("channel"), "error": str(exc)})


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
def _store_web_pending(action: str, client: dict, args: dict, requester: Optional[str],
                       reason: Optional[str] = None) -> str:
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
                                "requester": requester, "reason": reason, "created": now}
    return token


def _store_web_batch(items: list[dict], requester: Optional[str]) -> str:
    """Stash an on-demand batch under a web token (same store/eviction as single
    actions, tagged ``batch`` so the confirm path runs it selectively)."""
    import uuid
    now = time.time()
    for tok, e in list(_pace_web_pending.items()):
        if now - e["created"] > _WEB_PENDING_TTL:
            _pace_web_pending.pop(tok, None)
    while len(_pace_web_pending) >= _WEB_PENDING_MAX:
        _pace_web_pending.pop(min(_pace_web_pending, key=lambda t: _pace_web_pending[t]["created"]), None)
    token = uuid.uuid4().hex
    _pace_web_pending[token] = {"batch": True, "items": items, "requester": requester, "created": now}
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

    # 1) Confirm a staged PACE web action or batch (its own token store).
    if pending_token and pending_token in _pace_web_pending:
        entry = _pace_web_pending.pop(pending_token)
        if entry.get("batch"):
            from services import pace_proposals

            selection = pace_proposals.parse_plan_reply(message, len(entry["items"]))
            if selection is not None:
                if not pace_auth.confirm_actor_ok(entry.get("requester"), context):
                    return {"reply": "Only the person who requested this can confirm it."}
                reply = await pace_proposals.execute_plan_selection(
                    entry["items"], selection, context, origin="batch")
                return {"reply": reply}
            # Not an approval — the batch is superseded; fall through.
        elif is_affirmative(message):
            if not pace_auth.confirm_actor_ok(entry.get("requester"), context):
                return {"reply": "Only the person who requested this can confirm it."}
            try:
                reply = await _run_pace_action(
                    entry["action"], entry["client_id"], entry["args"], context,
                    reason=entry.get("reason"), requester=entry.get("requester"),
                    client_name=entry.get("client_name"))
            except Exception as exc:
                logger.warning("pace_web_action_failed", extra={"action": entry["action"], "error": str(exc)})
                reply = "Sorry — that action failed."
            return {"reply": reply, "client_id": entry["client_id"], "client_name": entry.get("client_name")}
        elif is_explicit_decline(message):
            # A single staged action the user explicitly rejected ("no"/"cancel")
            # — record the decline. A mere pivot to another question also
            # supersedes the pending, but is NOT logged as a decision.
            _log_declined({"action": entry["action"], "client_id": entry["client_id"],
                           "client_name": entry.get("client_name"), "args": entry["args"],
                           "requester": entry.get("requester"), "confirm": entry.get("reason")},
                          context)
        # Non-affirmative supersedes; fall through to normal handling.

    if not force and not is_pace_message(message):
        return None
    try:
        if is_personal_brief(message):
            return {"reply": await run_in_threadpool(personal_brief_text, context)}
        result = await _answer(message, history, sticky_client_id, context, "web", on_event, run_in_threadpool)
        batch = result.get("batch")
        if batch:
            token = _store_web_batch(batch["items"], batch["requester"])
            return {"reply": pace_batch.render_batch(batch["items"], batch["flags"],
                                                     batch.get("overflow", 0), bold="**"),
                    "pending_token": token}
        pending = result.get("pending")
        if pending:
            token = _store_web_pending(
                pending["name"], {"id": pending["client_id"], "name": pending["client_name"]},
                pending["args"], pending["requester"], reason=pending.get("confirm"),
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
