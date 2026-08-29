"""Durable chat history for the dashboard assistants (SerMaStr and PACE).

Backs `assistant_conversations` + `assistant_messages` (migration
`20260730120000`). Before this, a thread lived only in the browser's
sessionStorage and the last 12 turns were re-sent from the client on every
request — so closing the tab lost it, another device couldn't see it, and no
transcript survived for anyone to read afterwards.

Both surfaces share the store, told apart by `surface` ('sermastr' | 'pace').
Threads are many-per-user and titled from their first message.

**Ownership:** whoever typed a thread owns it. Reads are owner-or-admin
(`can_read`); writes are owner-only (`can_write`) — an admin may read a
colleague's conversation to diagnose a bad answer, but never post into it, so
a transcript always reflects one person's actual conversation. The backend
holds the service-role key, so RLS never sees the end user and these checks are
the enforcement point, not a second line of defence.

Persistence is wired in the **routers** (`routers/assistant.py`,
`routers/pace.py`) around the existing turn handlers rather than inside them:
`handle_chat`/`maybe_handle_web` already take history as a plain list, so the
router loads it from here instead of trusting the browser and appends both
messages afterwards. That keeps the two brains untouched and makes the same
persistence work identically for both personas.

Pure helpers (`derive_title`, `can_read`, `can_write`, `to_history`) are
unit-tested; everything else is thin Supabase I/O.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Turns loaded back as prompt history. Mirrors the browser's old slice(-12) and
# `assistant_chat._HISTORY_LIMIT` — the handlers re-trim, so this is just the
# read window.
HISTORY_TURNS = 12

# How many threads the history list returns per surface.
LIST_LIMIT = 50

_TITLE_MAX = 80
_WHITESPACE_RE = re.compile(r"\s+")

SURFACES = ("sermastr", "pace", "director")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def derive_title(message: str) -> str:
    """A thread's title from its first user message: one collapsed line, cut on
    a word boundary. Empty input yields a neutral placeholder rather than an
    empty row, so the history list never renders a blank entry."""
    text = _WHITESPACE_RE.sub(" ", (message or "").strip())
    if not text:
        return "New conversation"
    if len(text) <= _TITLE_MAX:
        return text
    cut = text[:_TITLE_MAX]
    # Prefer the last space so the title doesn't end mid-word; fall back to a
    # hard cut for text with no spaces at all (a pasted URL, say).
    space = cut.rfind(" ")
    if space > _TITLE_MAX // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def can_read(conversation: Optional[dict], actor_id: Optional[str], role: Optional[str]) -> bool:
    """Owner-or-admin. A missing conversation is unreadable (the caller turns
    that into a 404, so a wrong id and someone else's id look identical)."""
    if not conversation or not actor_id:
        return False
    if str(conversation.get("owner_id")) == str(actor_id):
        return True
    return role == "admin"


def can_write(conversation: Optional[dict], actor_id: Optional[str]) -> bool:
    """Owner-only — admins read transcripts, they don't add to them."""
    if not conversation or not actor_id:
        return False
    return str(conversation.get("owner_id")) == str(actor_id)


def to_history(rows: list[dict]) -> list[dict]:
    """Stored message rows → the {role, content} list the chat handlers take.

    Skips empty content so a failed turn that stored a blank reply can't inject
    an empty assistant message into the next prompt.
    """
    return [
        {"role": r["role"], "content": r["content"]}
        for r in rows or []
        if r.get("role") in ("user", "assistant") and (r.get("content") or "").strip()
    ]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def get_conversation(conversation_id: str) -> Optional[dict]:
    rows = (
        get_supabase()
        .table("assistant_conversations")
        .select("*")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def list_conversations(owner_id: str, surface: str, limit: int = LIST_LIMIT) -> list[dict]:
    """A user's live threads on one surface, most recently active first."""
    return (
        get_supabase()
        .table("assistant_conversations")
        .select("id, surface, client_id, title, created_at, updated_at")
        .eq("owner_id", owner_id)
        .eq("surface", surface)
        .is_("archived_at", "null")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []


def get_messages(conversation_id: str, limit: int = 500) -> list[dict]:
    """The full thread, oldest first — what the frontend renders on open."""
    return (
        get_supabase()
        .table("assistant_messages")
        .select("id, role, content, client_id, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .limit(limit)
        .execute()
    ).data or []


def client_names_for(rows: list[dict]) -> dict[str, str]:
    """{client_id: name} for a batch of conversation rows — one lookup so the
    history list can label threads by client without an N+1."""
    ids = list({r["client_id"] for r in rows or [] if r.get("client_id")})
    if not ids:
        return {}
    found = (
        get_supabase().table("clients").select("id, name").in_("id", ids).execute()
    ).data or []
    return {c["id"]: c["name"] for c in found}


def load_history(conversation_id: str, turns: int = HISTORY_TURNS) -> list[dict]:
    """The last `turns` messages as prompt history ({role, content}, oldest
    first). Read newest-first then reversed, so a long thread doesn't pull every
    row back just to discard the front."""
    rows = (
        get_supabase()
        .table("assistant_messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(turns)
        .execute()
    ).data or []
    return to_history(list(reversed(rows)))


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def create_conversation(
    owner_id: str, surface: str, first_message: str, client_id: Optional[str] = None
) -> dict:
    row = (
        get_supabase()
        .table("assistant_conversations")
        .insert(
            {
                "owner_id": owner_id,
                "surface": surface,
                "client_id": client_id,
                "title": derive_title(first_message),
            }
        )
        .execute()
    ).data
    return row[0] if row else {}


def append_message(
    conversation_id: str,
    role: str,
    content: str,
    client_id: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    get_supabase().table("assistant_messages").insert(
        {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "client_id": client_id,
            "meta": meta or {},
        }
    ).execute()


def touch(conversation_id: str, client_id: Optional[str] = None) -> None:
    """Bump `updated_at` (so the thread rises in the history list) and follow the
    conversation's current client. A turn that resolved no client leaves the
    stored one alone — portfolio-mode asides shouldn't unstick a client thread."""
    patch: dict = {"updated_at": "now()"}
    if client_id:
        patch["client_id"] = client_id
    get_supabase().table("assistant_conversations").update(patch).eq(
        "id", conversation_id
    ).execute()


def archive_conversation(conversation_id: str) -> None:
    """Soft-delete — the row survives for admin diagnosis, the owner stops
    seeing it."""
    get_supabase().table("assistant_conversations").update(
        {"archived_at": "now()"}
    ).eq("id", conversation_id).execute()


# ---------------------------------------------------------------------------
# The turn wrapper the routers use
# ---------------------------------------------------------------------------
def begin_turn(
    conversation_id: Optional[str],
    owner_id: str,
    surface: str,
    message: str,
    fallback_history: list[dict],
) -> tuple[Optional[str], list[dict]]:
    """Open (or resume) a thread for this turn and return (id, prompt history).

    Best-effort throughout: if the store is unreachable the turn still runs with
    the browser-supplied history, just unsaved — a chat that can't be persisted
    should degrade to the old behaviour, never fail in the user's face.

    `fallback_history` is what the browser sent. It's used only when there's no
    conversation yet (an older frontend, or the first turn of a new thread),
    since stored history is both authoritative and not client-controlled.
    """
    try:
        if conversation_id:
            history = load_history(conversation_id)
            append_message(conversation_id, "user", message)
            return conversation_id, history
        convo = create_conversation(owner_id, surface, message)
        cid = convo.get("id")
        if cid:
            append_message(cid, "user", message)
        return cid, list(fallback_history or [])
    except Exception as exc:
        logger.warning(
            "assistant_store_begin_failed",
            extra={"surface": surface, "conversation": conversation_id, "err": str(exc)},
        )
        return conversation_id, list(fallback_history or [])


def end_turn(
    conversation_id: Optional[str],
    reply: str,
    client_id: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """Store the assistant's reply and bump the thread. Best-effort — a failure
    here must not lose the user the answer they're already reading."""
    if not conversation_id:
        return
    try:
        append_message(conversation_id, "assistant", reply, client_id, meta)
        touch(conversation_id, client_id)
    except Exception as exc:
        logger.warning(
            "assistant_store_end_failed",
            extra={"conversation": conversation_id, "err": str(exc)},
        )
