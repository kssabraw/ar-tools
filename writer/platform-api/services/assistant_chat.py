"""In-app SerMaStr chat — the dashboard chatbox on Home.

Web twin of the Slack assistant (`services/slack_assistant`): the exact same
brain — client resolution, cross-module context providers, the Claude
interpret pass (Q&A + the action-tool registry), confirm-gated actions — but
spoken over the authenticated JSON endpoint in `routers/assistant.py` instead
of Slack events. Differences from the Slack path:

- Conversation history arrives from the browser (the transcript the chatbox
  holds), not `conversations.replies`.
- The client is *sticky*: once a message names a client, follow-ups that
  don't name one keep talking about it — the frontend echoes back the
  resolved `client_id` on every turn.
- Confirm-gated actions stage a one-time token (in-memory, single replica,
  TTL'd — same best-effort semantics as the Slack `_pending` store) instead
  of a (channel, thread_ts) key; the frontend confirms by sending an
  affirmative reply carrying the token.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Optional

from fastapi.concurrency import run_in_threadpool

from db.supabase_client import get_supabase
from services import slack_assistant

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 12  # prior turns folded into the prompt (mirrors the Slack cap)
_PENDING_TTL_SECONDS = 15 * 60
_PENDING_MAX = 200  # hard cap so an abandoned-tab flood can't grow the dict forever

# Pending confirm-gated actions awaiting a "yes", keyed by one-time token.
# In-memory / single-process (PLATFORM is one replica) + best-effort: a redeploy
# drops pending confirmations, which just means the user re-asks. Never executes
# a confirm-gated action without an explicit affirmative carrying the token.
_pending: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Pure-ish helpers (deterministic given `now`) — unit-tested.
# ---------------------------------------------------------------------------
def store_pending(action: str, client: dict, args: Optional[dict], now: Optional[float] = None) -> str:
    """Stage a confirm-gated action; returns the one-time confirm token."""
    now = time.time() if now is None else now
    # Evict expired entries (and oldest-first past the cap) on every write.
    for token, entry in list(_pending.items()):
        if now - entry["created"] > _PENDING_TTL_SECONDS:
            _pending.pop(token, None)
    while len(_pending) >= _PENDING_MAX:
        oldest = min(_pending, key=lambda t: _pending[t]["created"])
        _pending.pop(oldest, None)
    token = secrets.token_urlsafe(16)
    _pending[token] = {
        "action": action,
        "client_id": client["id"],
        "client_name": client.get("name"),
        "args": args,
        "created": now,
    }
    return token


def take_pending(token: Optional[str], now: Optional[float] = None) -> Optional[dict]:
    """Pop and return a staged action if the token is live; None otherwise."""
    if not token:
        return None
    now = time.time() if now is None else now
    entry = _pending.pop(token, None)
    if entry and now - entry["created"] > _PENDING_TTL_SECONDS:
        return None
    return entry


def resolve_chat_client(
    message: str, sticky_client_id: Optional[str], clients: list[dict]
) -> Optional[dict]:
    """Which client is this turn about?

    A client named in the message wins (so "and how about Acme?" switches
    mid-conversation); otherwise fall back to the conversation's sticky client.
    """
    named = slack_assistant.resolve_client(message, clients)
    if named:
        return named
    if sticky_client_id:
        return next((c for c in clients if c.get("id") == sticky_client_id), None)
    return None


# ---------------------------------------------------------------------------
# The chat turn.
# ---------------------------------------------------------------------------
def _list_clients() -> list[dict]:
    return (
        get_supabase().table("clients").select("id, name, website_url").execute()
    ).data or []


async def handle_chat(
    message: str,
    history: list[dict],
    sticky_client_id: Optional[str],
    pending_token: Optional[str],
) -> dict:
    """Process one chatbox turn; returns the response payload dict.

    Shape: {reply, client_id?, client_name?, pending_token?} — `pending_token`
    is set when a confirm-gated action was staged and the frontend should offer
    a Confirm affordance (an affirmative reply carrying the token executes it).
    """
    history = history[-_HISTORY_LIMIT:]

    # 1) Confirmation of a staged action — the token pins the exact action +
    # client, so the "yes" needn't name anything.
    pending = take_pending(pending_token)
    if pending and slack_assistant.is_affirmative(message):
        reply = await slack_assistant._run_action(
            pending["action"], pending["client_id"], pending.get("args")
        )
        return {
            "reply": reply,
            "client_id": pending["client_id"],
            "client_name": pending.get("client_name"),
        }
    # Any other message supersedes the pending confirmation (already popped).

    clients = await run_in_threadpool(_list_clients)
    client = resolve_chat_client(message, sticky_client_id, clients)
    if not client:
        names = ", ".join(c["name"] for c in clients[:8] if c.get("name"))
        return {
            "reply": "Which client do you mean? Name them in your message"
            + (f" — e.g. {names}." if names else "."),
        }

    context = await run_in_threadpool(slack_assistant.build_context, client["id"])
    kind, payload = await slack_assistant.interpret(
        message, client, context, history, style="web"
    )
    base = {"client_id": client["id"], "client_name": client.get("name")}

    if kind == "action":
        name, args = payload["name"], payload["args"]
        meta = slack_assistant._ACTIONS[name]
        confirm_phrase = None
        if meta.get("stage"):
            # Resolve the target BEFORE the confirm (exact task, matched
            # assignee) — guards / ambiguity answer immediately instead.
            outcome, staged = await meta["stage"](client["id"], args)
            if outcome == "reply":
                return {**base, "reply": staged}
            args = staged
            confirm_phrase = args.pop("_confirm", None)
        if meta["paid"]:
            token = store_pending(name, client, args)
            phrase = confirm_phrase or f"{meta['label']} ({meta.get('note', 'uses API budget')})"
            return {
                **base,
                "reply": f"This will {phrase} for **{client['name']}**. Confirm to proceed.",
                "pending_token": token,
            }
        return {**base, "reply": await slack_assistant._run_action(name, client["id"], args)}

    return {**base, "reply": payload}
