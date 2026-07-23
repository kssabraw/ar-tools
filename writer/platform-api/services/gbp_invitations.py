"""Accept GBP manager invitations for the connected agency account.

When a client grants access, they add the connected (white-label) account as a
**Manager** on their Business Profile — which sends that account a *pending
invitation* it must accept before it can post. This lets the app accept those
invitations programmatically (v1 Account Management API, ``business.manage``),
so onboarding is: client adds the account → staff clicks "Accept" in the app →
the listing is manageable. No logging into the neutral Google account.

Uses the OAuth token from ``services/gbp_auth`` (the connected account). Pure
``parse_invitation`` is unit-tested; live calls are best-effort.

Refs: developers.google.com/my-business/reference/accountmanagement/rest/v1/accounts.invitations
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_V1 = "https://mybusinessaccountmanagement.googleapis.com/v1"
_TIMEOUT = 30


def parse_invitation(inv: dict) -> dict:
    """Map a v1 Invitation to {name, role, business}. Pure (unit-tested)."""
    inv = inv or {}
    target_loc = inv.get("targetLocation") or {}
    target_acct = inv.get("targetAccount") or {}
    business = (
        target_loc.get("locationName")
        or target_loc.get("address")
        or target_acct.get("accountName")
        or "a business"
    )
    return {"name": inv.get("name"), "role": inv.get("role"), "business": business}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_pending() -> list[dict]:
    """List pending manager invitations across all of the connected account's
    accounts. Best-effort: returns [] if not connected / on any API error."""
    from services import gbp_auth  # lazy

    try:
        token = gbp_auth.access_token()
    except Exception as exc:  # noqa: BLE001 — not connected / no creds
        logger.info("gbp_invitations.no_token", extra={"error": str(exc)})
        return []
    out: list[dict] = []
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_headers(token)) as client:
            acct_resp = client.get(f"{_V1}/accounts")
            acct_resp.raise_for_status()
            for acct in acct_resp.json().get("accounts", []) or []:
                name = acct.get("name")
                if not name:
                    continue
                inv_resp = client.get(f"{_V1}/{name}/invitations")
                if inv_resp.status_code != 200:
                    continue
                for inv in inv_resp.json().get("invitations", []) or []:
                    out.append(parse_invitation(inv))
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_invitations.list_failed", extra={"error": str(getattr(exc, "response", exc))})
    return out


def accept_all() -> dict:
    """Accept every pending invitation. Returns {accepted, businesses, pending}."""
    from services import gbp_auth  # lazy

    pending = list_pending()
    if not pending:
        return {"accepted": 0, "businesses": [], "pending": 0}
    try:
        token = gbp_auth.access_token()
    except Exception:  # noqa: BLE001
        return {"accepted": 0, "businesses": [], "pending": len(pending)}
    accepted: list[Optional[str]] = []
    with httpx.Client(timeout=_TIMEOUT, headers=_headers(token)) as client:
        for inv in pending:
            name = inv.get("name")
            if not name:
                continue
            try:
                resp = client.post(f"{_V1}/{name}:accept", json={})
                if resp.status_code == 200:
                    accepted.append(inv.get("business"))
            except Exception as exc:  # noqa: BLE001 — one failure must not stop the rest
                logger.info("gbp_invitations.accept_failed", extra={"name": name, "error": str(exc)})
    logger.info("gbp_invitations.accepted", extra={"count": len(accepted)})
    return {"accepted": len(accepted), "businesses": [b for b in accepted if b], "pending": len(pending)}
