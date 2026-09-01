"""DORA — the Director of Operations conversational persona (answer-only).

Owner ruling 2026-08-29: the Director of Operations gets its OWN surface (the
``/director`` web chat page + a ``#dora`` Slack channel), not just a lens inside
SerMaStr. This is that persona — a thin conversational wrapper over the existing
read-only cross-agent read model (``services/director/read_model.build_read_model``).

DORA is READ-ONLY, answer-only. It observes how work flows across the agency's
agents — SerMaStr (proposes strategy), PACE (executes delivery), QA (judges
quality), the autonomy executor, and the deterministic producers — and
reports/flags where work snags BETWEEN them. It never reassigns, reschedules,
resolves, or executes: there are NO tools and NO confirm-gated actions here
(contrast ``services/pace_agent.py``, which is the executing sibling). Strategy
questions defer to SerMaStr, delivery-execution questions to PACE, in prose.

Gated on ``settings.director_enabled`` at the router; while off, ``/director/*``
503s and the sidebar entry stays hidden.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services.director import read_model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persona prompt
# ---------------------------------------------------------------------------
_DORA_SYSTEM = (
    "You are DORA — Director of Operations, Reconciliation & Awareness — for an "
    "SEO agency. You watch how work flows ACROSS the agency's agents (SerMaStr "
    "proposes strategy, PACE executes delivery, QA judges quality, the autonomy "
    "executor acts under tight limits, and deterministic producers open tasks) "
    "and across the native task board. You are the cross-agent lens: you notice "
    "where work snags BETWEEN agents — an approved strategy proposal nobody "
    "placed, an autonomy candidate left unactioned, content shipped without brand "
    "context, two agents acting on the same target, QA sitting idle.\n\n"
    "READ-ONLY. You observe and flag; you never reassign, reschedule, resolve, "
    "execute, or change anything. When something needs doing, name the agent or "
    "surface that owns it (PACE moves tasks and chases delivery; SerMaStr decides "
    "strategy; QA reviews deliverables) and OFFER to point the person there — "
    "never claim you did it yourself.\n\n"
    "THE READ MODEL. You are handed a cross-agent read model as JSON. Its "
    "`flow.flags` list is the headline — the open seams, each with a `seam` type, "
    "a `client_id`, `evidence`, and `since`. The other blocks are the supporting "
    "detail: `delivery` and `assignment` (the PACE board — overdue / stuck / "
    "unassigned / workload), `strategy` (approved-but-unplaced proposals), "
    "`autonomy` (proposed-but-unactioned candidates), `producers` (task sources, "
    "including unrecognized ones), `interventions` (outcome tracking), `qa` "
    "(whether anything is reaching review at all), `content` (degraded ships), "
    "`duplicates` (same-target collisions).\n\n"
    "ENUMERATE, DON'T SUMMARIZE. When asked what's snagged / where the bottleneck "
    "is / where two agents overlap / how the operation is flowing, LIST the actual "
    "seams and rows from the read model — name the client, the seam, and the "
    "evidence per item. Group by what's most blocking. Give a bare count only when "
    "the read model genuinely has no matching rows.\n\n"
    "GROUNDING. Only state flags, clients, and rows that appear in the read model. "
    "Be concrete and specific; skip filler. If asked about something the read "
    "model doesn't cover, say so plainly and point at the agent that would know.\n\n"
    "FORMATTING: you are replying in Slack, which does NOT render standard "
    "Markdown. Never use **bold**, # headers, or [text](url) links — Slack "
    "ignores or mangles them. Use Slack's own mrkdwn instead: *bold* (single "
    "asterisks), _italic_, `code`, bullet lines starting with \"- \" or \"• \", "
    "and <https://example.com|link text> for links. NEVER use a Markdown pipe "
    "table (| Seam | Client |...) or a --- horizontal rule — Slack renders "
    "neither; a table shows up as a wall of literal pipe characters. For a seam "
    "list, use one bullet per seam instead, bolding the seam and folding the rest "
    "inline. Keep replies short and scannable — a few lines or a tight list, not "
    "walls of text."
)

# Appended instead of the Slack formatting rule above when DORA is answering in
# the dashboard chat (routers/director.py `style="web"`) rather than Slack — same
# brain, different room. Mirrors pace_agent._PACE_WEB_STYLE.
_DORA_WEB_STYLE = (
    "\n\nFORMATTING OVERRIDE: you are answering in the AR Tools dashboard chat "
    "(a web app), NOT Slack. Ignore the Slack mrkdwn rule above — format with "
    "standard Markdown instead (**bold**, `-` bullets, [text](url) links), and "
    "never mention Slack, threads, or channels."
)

# Human-readable seam labels for the deterministic opening brief (the LLM path
# gets the raw seam types in the JSON and names them itself).
_SEAM_LABELS = {
    "strategist_proposal_pending": "Strategy proposal waiting on an approve/dismiss decision",
    "strategist_approved_unplaced": "Approved strategy proposal not placed on the board",
    "autonomy_proposed_unactioned": "Autonomy candidate proposed but not acted on",
    "content_shipped_degraded": "Content shipped without full brand/voice context",
    "duplicate_target": "Two agents acting on the same target",
    "qa_idle": "QA idle — nothing reaching review",
    "unwatched_seam": "Tasks from an unrecognized producer source",
}


# ---------------------------------------------------------------------------
# Context (the cross-agent read model — deterministic, best-effort)
# ---------------------------------------------------------------------------
def build_context(client_id: Optional[str], today: Optional[date] = None) -> dict:
    """DORA's grounding: the full cross-agent read model for one client
    (``client_id`` set) or the whole portfolio (``None``). Best-effort — the read
    model isolates each provider itself and never raises."""
    return read_model.build_read_model(client_id, today)


def _all_clients() -> list[dict]:
    return (get_supabase().table("clients").select("id, name").execute()).data or []


def _client_names(client_ids: list) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


def _resolve_scope(question: str, sticky_client_id: Optional[str]) -> tuple[str, Optional[str], Optional[str]]:
    """Pick the scope for a turn: a client named in the message wins (most
    specific), else the conversation's sticky client, else the whole-agency
    portfolio. Blocking (DB read) — call via a runner. Returns
    (scope, client_id, client_name)."""
    from services.slack_assistant import resolve_client

    clients = _all_clients()
    named = resolve_client(question, clients)
    if named:
        return "client", named["id"], named.get("name")
    if sticky_client_id:
        sticky = next((c for c in clients if c.get("id") == sticky_client_id), None)
        if sticky:
            return "client", sticky["id"], sticky.get("name")
    return "portfolio", None, None


# ---------------------------------------------------------------------------
# Deterministic opening brief (the /director empty state — no LLM)
# ---------------------------------------------------------------------------
def _render_flags(flags: list[dict]) -> str:
    names = _client_names([f.get("client_id") for f in flags])
    n = len(flags)
    lines = [f"*{n} open seam flag{'s' if n != 1 else ''} across the agents:*"]
    for f in flags[:12]:
        label = _SEAM_LABELS.get(f.get("seam"), f.get("seam") or "seam")
        line = f"• {label}"
        who = names.get(f.get("client_id")) if f.get("client_id") else None
        if who:
            line += f" — *{who}*"
        ev = f.get("evidence")
        if ev:
            line += f" ({ev})"
        lines.append(line)
    if n > 12:
        lines.append(f"…and {n - 12} more.")
    return "\n".join(lines)


def opening_brief_text() -> str:
    """A deterministic portfolio seam digest for the /director page empty state —
    the open cross-agent seam flags right now, no LLM call. Best-effort."""
    try:
        model = build_context(None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("director_brief_failed", extra={"error": str(exc)})
        return ""
    flags = ((model.get("flow") or {}).get("flags")) or []
    if not flags:
        return "All clear across the agents — no open cross-agent seam flags right now."
    return _render_flags(flags)


def _fallback_text(model: Optional[dict]) -> str:
    flags = ((model or {}).get("flow") or {}).get("flags") or []
    if not flags:
        return "Nothing's snagged across the agents right now — no open seam flags."
    return "DORA couldn't compose a full answer just now. Here's the raw read:\n\n" + _render_flags(flags)


# ---------------------------------------------------------------------------
# LLM interpret (single call — read-only, no tools)
# ---------------------------------------------------------------------------
async def interpret_dora(question: str, model: dict, history: Optional[list[dict]] = None,
                         style: str = "slack", on_event=None, scope_line: str = "") -> str:
    """One DORA turn: hand the LLM the cross-agent read model + the question and
    return a text answer. No tools, no actions — DORA only observes. Sonnet
    (`director_model`)."""
    import json

    import anthropic

    from services import anthropic_failover
    from services.slack_assistant.llm import _one_llm_call, format_history

    blocks = []
    if history:
        blocks.append("Conversation so far:\n" + format_history(history))
    if scope_line:
        blocks.append(scope_line)
    blocks.append("Cross-agent read model (JSON):\n" + json.dumps(model, default=str, ensure_ascii=False))
    blocks.append(f"Latest message: {question}")
    messages = [{"role": "user", "content": "\n\n".join(blocks)}]
    system = _DORA_SYSTEM + (_DORA_WEB_STYLE if style == "web" else "")

    async def on_text(delta: str) -> None:
        await on_event({"type": "text", "text": delta})

    clients = anthropic_failover.build_async_clients(timeout=60.0, max_retries=2)
    kw = {"model": settings.director_model, "max_tokens": settings.director_max_tokens}
    try:
        resp = await anthropic_failover.call_failover(
            clients,
            lambda c: _one_llm_call(c, system, messages, [], kw, on_text if on_event else None),
            log_tag="director_agent",
        )
    except anthropic.APIStatusError as exc:
        if exc.status_code in (429, 529, 503):
            return "DORA is busy right now — try again in a moment."
        raise

    parts = [b.text for b in (resp.content if resp else []) if getattr(b, "type", None) == "text"]
    reply = "\n".join(parts).strip() or "I couldn't work that out — try rephrasing."
    if resp is not None and getattr(resp, "stop_reason", None) == "max_tokens":
        reply += "\n\n_…I hit my reply-length limit — say “continue” and I'll pick up where I left off._"
    return reply


# ---------------------------------------------------------------------------
# Turn resolution + web entry
# ---------------------------------------------------------------------------
async def _answer(question: str, history: Optional[list[dict]], sticky_client_id: Optional[str],
                  style: str, on_event, runner) -> dict:
    """One DORA turn, answer-only. Resolves scope, builds the read model, and
    interprets. Returns ``{"reply": str, "client_id"?, "client_name"?}``."""
    scope, client_id, client_name = await runner(_resolve_scope, question, sticky_client_id)
    model = await runner(build_context, client_id)
    base = {"client_id": client_id, "client_name": client_name} if client_id else {}
    if scope == "portfolio":
        scope_line = "Scope: the whole agency — cross-agent flow across every client board."
    else:
        scope_line = f"Scope: the client *{client_name or 'this client'}* — its cross-agent flow."
    try:
        reply = await interpret_dora(question, model, history, style, on_event, scope_line)
    except Exception as exc:  # noqa: BLE001
        logger.warning("director_interpret_failed", extra={"scope": scope, "error": str(exc)})
        return {**base, "reply": _fallback_text(model)}
    return {**base, "reply": reply}


async def maybe_handle_web(message: str, history: Optional[list[dict]], sticky_client_id: Optional[str],
                           on_event=None) -> dict:
    """Handle a DORA web chat turn. Answer-only, so it always returns a reply dict
    (never None). The deterministic reads (client list, read model) do blocking
    Supabase I/O, so they're pushed to a threadpool to keep the request loop free
    — matching pace_agent.maybe_handle_web's convention."""
    from fastapi.concurrency import run_in_threadpool

    try:
        return await _answer(message, history, sticky_client_id, "web", on_event, run_in_threadpool)
    except Exception as exc:  # noqa: BLE001
        logger.warning("director_web_failed", extra={"error": str(exc)})
        return {"reply": "Sorry — DORA hit an error."}


# ---------------------------------------------------------------------------
# Slack entry (dedicated DORA app — /slack/director/events)
# ---------------------------------------------------------------------------
async def _run_direct(fn, *args):
    """Runner shim for the Slack path — its reads are already off the request loop
    (a background task), so blocking calls run inline (mirrors the web path's
    run_in_threadpool)."""
    return fn(*args)


async def handle_director_message(event: dict) -> None:
    """Inbound handler for the dedicated DORA Slack app (``/slack/director/events``).
    That app lives only in the ``#dora`` channel, so every plain human message
    there is DORA's to answer. Read-only — no actor, no permissions, no actions;
    DORA just answers cross-agent questions and posts back under its own bot
    token. Best-effort; never surfaces into the ack path."""
    from services import notifications
    from services.slack_assistant import post_message as _send, strip_mention

    try:
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        question = strip_mention(event.get("text", ""))
        if not (channel and question):
            return
        result = await _answer(question, None, None, "slack", None, _run_direct)
        reply = result.get("reply") or "I couldn't work that out — try rephrasing."
        await _send(channel, reply, thread_ts, token=notifications.director_bot_token())
    except Exception as exc:  # noqa: BLE001 — never surface into the ack path
        logger.warning("director_inbound_failed",
                       extra={"channel": event.get("channel"), "error": str(exc)})
