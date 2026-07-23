"""In-app "Connect Google Business Profile" OAuth endpoints.

The SaaS flow that replaces the CLI token-grab:
  * ``GET  /gbp/oauth/status``     — is the OAuth client configured + connected?
  * ``GET  /gbp/oauth/start``      — (staff) returns Google's consent URL to redirect to
  * ``GET  /gbp/oauth/callback``   — public; Google redirects here with the code,
                                     we exchange + store the refresh token, then
                                     redirect the browser back to the app
  * ``POST /gbp/oauth/disconnect`` — (staff) forget the stored token

The callback is public (a top-level browser redirect from Google carries no app
JWT); it's protected by the signed ``state`` (CSRF + freshness) and the exchange
requires the client secret. Independent of the ``gbp_posts_enabled`` flag so you
can connect during setup, before flipping the feature on.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from middleware.auth import require_auth, require_staff
from services import gbp_auth, gbp_invitations, gbp_oauth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gbp-oauth"])


@router.get("/gbp/oauth/status")
async def oauth_status(auth: dict = Depends(require_auth)):
    """Connection status for the Connect UI (+ which auth mode is active)."""
    status = gbp_oauth.get_status()
    status["auth_mode"] = gbp_auth.auth_mode()
    return status


@router.get("/gbp/oauth/start")
async def oauth_start(return_to: str = Query(""), auth: dict = Depends(require_staff)):
    """Return the Google consent URL to redirect the browser to. Staff-gated."""
    if not gbp_oauth.is_client_configured():
        return {"error": "oauth_client_not_configured"}
    ts = int(datetime.now(timezone.utc).timestamp())
    state = gbp_oauth.sign_state(gbp_oauth.safe_return_to(return_to), secrets.token_urlsafe(8), ts)
    return {"auth_url": gbp_oauth.build_auth_url(state)}


@router.get("/gbp/oauth/callback")
async def oauth_callback(
    code: str = Query(""), state: str = Query(""), error: str = Query(""),
):
    """Public callback — Google redirects here. Validate state, exchange the code,
    store the refresh token, then bounce the browser back into the app."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    data = gbp_oauth.parse_state(state, now_ts)
    return_to = gbp_oauth.safe_return_to((data or {}).get("r"))
    sep = "&" if "?" in return_to else "?"
    if error or not code or data is None:
        reason = error or ("bad_state" if data is None else "no_code")
        return RedirectResponse(f"{return_to}{sep}gbp_error={reason}")
    try:
        result = gbp_oauth.exchange_code(code)
        gbp_oauth.store(result["refresh_token"], result.get("account_email"), None)
        logger.info("gbp_oauth.connected", extra={"account_email": result.get("account_email")})
        return RedirectResponse(f"{return_to}{sep}gbp_connected=1")
    except Exception as exc:  # noqa: BLE001 — surface a clean error to the UI
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("gbp_oauth.callback_failed", extra={"error": str(detail)})
        return RedirectResponse(f"{return_to}{sep}gbp_error=connect_failed")


@router.post("/gbp/oauth/disconnect")
async def oauth_disconnect(auth: dict = Depends(require_staff)):
    """Forget the stored refresh token (falls back to service account / env)."""
    gbp_oauth.clear()
    return {"ok": True}


@router.get("/gbp/oauth/invitations")
async def list_invitations(auth: dict = Depends(require_staff)):
    """Pending GBP manager invitations the connected account has received
    (i.e. clients who added it as a Manager but not yet accepted)."""
    return {"invitations": gbp_invitations.list_pending()}


@router.post("/gbp/oauth/accept-invitations")
async def accept_invitations(auth: dict = Depends(require_staff)):
    """Accept all pending manager invitations so the listings become postable."""
    return gbp_invitations.accept_all()
