"""In-app "Connect Google Business Profile" OAuth flow (agency account).

The SaaS "Sign in with Google" model: an admin clicks Connect → Google's consent
screen → we exchange the code for a long-lived **refresh token** and store it in
``gbp_oauth_credentials``. ``services/gbp_auth`` then mints API tokens from it —
no CLI token-grab, no per-client OAuth, no service-account Manager step. One
agency Google account (that already manages the client listings) authorizes once.

Flow:
  1. ``build_auth_url(state)`` → Google consent URL (scope ``business.manage``,
     ``access_type=offline`` + ``prompt=consent`` so a refresh token is returned).
  2. Google redirects the browser to ``google_oauth_redirect_uri`` with a code.
  3. ``exchange_code(code)`` → refresh token + the account email → ``store()``.

State is a signed token (HMAC over ``{nonce, return_to, ts}``) so the public
callback needs no server-side session — validated + freshness-checked, and
``return_to`` is constrained to the app origin (no open redirect). Pure helpers
(``sign_state``/``parse_state``) are unit-tested.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"
_SCOPES = "https://www.googleapis.com/auth/business.manage openid email"
_STATE_MAX_AGE_S = 600
_PROVIDER = "gbp"


# ── config / status ──────────────────────────────────────────────────────────
def is_client_configured() -> bool:
    """Whether the OAuth *client* (id/secret/redirect) is set up so a Connect can
    even start. Pure."""
    return bool(
        settings.google_oauth_client_id
        and settings.google_oauth_client_secret
        and settings.google_oauth_redirect_uri
    )


def get_refresh_token() -> Optional[str]:
    """The stored agency refresh token, or None. Never raises (safe pre-connect)."""
    try:
        rows = (
            get_supabase().table("gbp_oauth_credentials")
            .select("refresh_token").eq("provider", _PROVIDER).limit(1).execute().data
        )
        return rows[0]["refresh_token"] if rows else None
    except Exception:  # noqa: BLE001 — no DB / not connected yet
        return None


def get_status() -> dict:
    """Connection status for the UI: whether the client is configured + connected,
    and the connected account email."""
    connected = False
    email = None
    try:
        rows = (
            get_supabase().table("gbp_oauth_credentials")
            .select("account_email, updated_at").eq("provider", _PROVIDER).limit(1).execute().data
        )
        if rows:
            connected = True
            email = rows[0].get("account_email")
    except Exception:  # noqa: BLE001
        pass
    return {"client_configured": is_client_configured(), "connected": connected, "account_email": email}


def store(refresh_token: str, account_email: Optional[str], user_id: Optional[str]) -> None:
    get_supabase().table("gbp_oauth_credentials").upsert(
        {"provider": _PROVIDER, "refresh_token": refresh_token, "account_email": account_email,
         "connected_by": user_id, "updated_at": "now()"},
        on_conflict="provider",
    ).execute()


def clear() -> None:
    get_supabase().table("gbp_oauth_credentials").delete().eq("provider", _PROVIDER).execute()


# ── signed state (pure, unit-tested) ─────────────────────────────────────────
def _secret() -> bytes:
    return (settings.supabase_service_role_key or "gbp-oauth-state").encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def sign_state(return_to: str, nonce: str, ts: int) -> str:
    payload = _b64e(json.dumps({"r": return_to, "n": nonce, "t": ts}).encode())
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def parse_state(state: str, now_ts: int) -> Optional[dict]:
    """Validate a signed state and return its payload, or None if bad/expired."""
    try:
        payload, sig = state.split(".", 1)
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_b64d(payload))
        if now_ts - int(data.get("t", 0)) > _STATE_MAX_AGE_S:
            return None
        return data
    except Exception:  # noqa: BLE001 — malformed
        return None


def safe_return_to(return_to: Optional[str]) -> str:
    """Constrain the post-connect redirect to the app origin (no open redirect)."""
    base = settings.app_base_url or ""
    if return_to and base and return_to.startswith(base):
        return return_to
    return base or "/"


# ── Google calls ─────────────────────────────────────────────────────────────
def build_auth_url(state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an auth code for tokens + the account email. Raises on failure."""
    with httpx.Client(timeout=30) as client:
        resp = client.post(_TOKEN_ENDPOINT, data={
            "code": code, "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        tokens = resp.json()
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("no_refresh_token")  # re-consent needed
        email = None
        access_token = tokens.get("access_token")
        if access_token:
            try:
                ui = client.get(_USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"})
                if ui.status_code == 200:
                    email = ui.json().get("email")
            except Exception:  # noqa: BLE001 — email is best-effort
                pass
    return {"refresh_token": refresh_token, "account_email": email}
