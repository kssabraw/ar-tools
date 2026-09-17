"""Social Media module — per-client PostForMe project API keys (ADR-0001 provider swap).

A PostForMe API key is scoped to one Project, and we run one Project per client, so the
key is the client-isolation boundary. It's a secret, kept in ``social_client_credentials``
(RLS/service-role only) — never on ``clients`` (which is ``select("*")``-ed to the
frontend) and never returned to the UI, which only ever sees a ``{configured}`` status.

Setting a key validates it against PostForMe (``check_auth``) before storing, then stamps
a ``clients.social_profile_id = 'postforme'`` marker so the publish path's existing
"is this client connected" gate (which reads that column) passes unchanged.

Provisioning is manual: PostForMe has no project/key-management API, so an admin creates
the client's Project + key in the dashboard and pastes the key in.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

_MARKER = "postforme"  # stored in clients.social_profile_id as the "connected" flag


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def get_client_key(client_id: str) -> Optional[str]:
    """The client's stored PostForMe project key, or None. Secret — callers must never
    return this to the frontend."""
    rows = (
        _sb().table("social_client_credentials").select("api_key")
        .eq("client_id", client_id).limit(1).execute()
    ).data or []
    return (rows[0].get("api_key") if rows else None) or None


def status(client_id: str) -> dict:
    """Non-secret connection status for the UI: whether a key is set + the active provider."""
    return {
        "configured": bool(get_client_key(client_id)),
        "provider": (settings.social_posting_provider or "postpeer").lower(),
    }


def set_client_key(client_id: str, api_key: str) -> dict:
    """Validate a PostForMe project key (live ``check_auth``) and store it for the client,
    stamping the ``social_profile_id`` connected-marker. A bad key raises before anything is
    stored. Blocking (one network call) — call via ``run_in_threadpool`` from an async route."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="social_key_required")

    from services.social.postforme_adapter import PostForMeAdapter

    # Validate before persisting — raises 502 postforme_auth_failed on a bad key.
    PostForMeAdapter(api_key=api_key).check_auth()

    sb = _sb()
    sb.table("social_client_credentials").upsert(
        {
            "client_id": client_id,
            "provider": "postforme",
            "api_key": api_key,
            "updated_at": "now()",
        },
        on_conflict="client_id",
    ).execute()
    sb.table("clients").update(
        {"social_profile_id": _MARKER, "updated_at": "now()"}
    ).eq("id", client_id).execute()
    logger.info("social.postforme_key_set", extra={"client_id": client_id})
    return status(client_id)


def delete_client_key(client_id: str) -> dict:
    """Remove the client's PostForMe key and clear the connected-marker (only if it's ours —
    never clobber a real PostPeer profile id)."""
    sb = _sb()
    sb.table("social_client_credentials").delete().eq("client_id", client_id).execute()
    rows = (
        sb.table("clients").select("social_profile_id").eq("id", client_id).limit(1).execute()
    ).data or []
    if rows and rows[0].get("social_profile_id") == _MARKER:
        sb.table("clients").update(
            {"social_profile_id": None, "updated_at": "now()"}
        ).eq("id", client_id).execute()
    logger.info("social.postforme_key_cleared", extra={"client_id": client_id})
    return status(client_id)
