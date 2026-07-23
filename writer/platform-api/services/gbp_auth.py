"""GBP API authentication — OAuth user token OR the agency service account.

Google's Business Profile API is OAuth-first: a bare service account is often
NOT accepted as a listing Manager the way it is for Search Console. So the Posts
path supports **either** auth model, selected by config:

  * **OAuth (preferred for GBP)** — when ``google_oauth_client_id`` +
    ``google_oauth_client_secret`` + ``gbp_oauth_refresh_token`` are set, we mint
    the API token from a long-lived refresh token belonging to the **agency
    Google account** that already manages the client listings. With a Google
    Workspace account the OAuth app is published **Internal** (no verification,
    tokens don't expire), and one consent covers every client — no per-client
    OAuth and no "add the service account as a Manager" step. Grab the refresh
    token once with ``scripts/get_gbp_refresh_token.py``.

  * **Service account (fallback)** — the agency service account used for GSC
    (``business.manage`` scope), added as a Manager per listing.

Only the token-minting is centralized here; the v4 REST calls in
``gbp_posts_api`` are identical either way. GSC + GBP-metrics are untouched.

Pure selectors (``oauth_configured``, ``auth_mode``) are unit-tested.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/business.manage"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def stored_refresh_token() -> Optional[str]:
    """The agency refresh token: the ``GBP_OAUTH_REFRESH_TOKEN`` env override
    first, else the one captured by the in-app Connect flow (DB). None if neither.

    Only consulted when the OAuth client id/secret are set (see ``oauth_configured``),
    so the DB read never runs in the service-account-only path."""
    if settings.gbp_oauth_refresh_token:
        return settings.gbp_oauth_refresh_token
    from services import gbp_oauth  # lazy; None-safe pre-connect

    return gbp_oauth.get_refresh_token()


def oauth_configured() -> bool:
    """Whether a complete OAuth credential set is available (client id + secret,
    plus a refresh token from env or the in-app Connect flow)."""
    return bool(
        settings.google_oauth_client_id
        and settings.google_oauth_client_secret
        and stored_refresh_token()
    )


def auth_mode() -> str:
    """Which auth model the GBP API will use: 'oauth' or 'service_account'. Pure."""
    return "oauth" if oauth_configured() else "service_account"


def is_configured() -> bool:
    """Whether *some* usable GBP credential exists (OAuth set, or the SA key)."""
    if oauth_configured():
        return True
    from services import gbp_performance_service as gbp  # lazy: avoids google import at load

    return gbp.gsc_service.is_configured()


def credentials():
    """Build API credentials — OAuth user creds when configured, else the agency
    service account. Lazy Google imports so this module loads without them."""
    if oauth_configured():
        from google.oauth2.credentials import Credentials  # noqa: PLC0415

        return Credentials(
            token=None,
            refresh_token=stored_refresh_token(),
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            token_uri=_TOKEN_URI,
            scopes=SCOPES,
        )
    from services import gbp_performance_service as gbp  # noqa: PLC0415

    return gbp._credentials()


def access_token() -> str:
    """Mint a bearer token for the v4 API (refreshes the selected credentials)."""
    from google.auth.transport.requests import Request  # noqa: PLC0415

    creds = credentials()
    creds.refresh(Request())
    return creds.token
