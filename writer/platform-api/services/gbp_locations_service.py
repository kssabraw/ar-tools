"""GBP location discovery + per-client registration (OAuth or service account).

The Compose picker posts to a ``gbp_locations`` row (``access_status='ok'``).
Under the OAuth-as-agency-account model nothing populates that table — the
connected account manages many listings and the app doesn't yet know which
listing belongs to which client. This module closes that gap:

  * ``resolve_connected_locations()`` — list every listing the *connected*
    account manages (v1 Account Management ``accounts.list`` → v1 Business
    Information ``accounts.locations.list``), using whichever credential
    ``gbp_auth`` selects (OAuth preferred, service account fallback). Best-effort:
    any API error returns an empty list + a detail string, never raises.
  * ``register_location(client_id, …)`` — assign one resolved listing to a client
    (upsert into ``gbp_locations`` with ``access_status='ok'``), so it shows up in
    the Compose location picker.
  * ``unregister_location`` — drop a registered row.

Distinct from ``gbp_performance_service.resolve_locations`` (service-account-only,
gated on the dormant metrics path) — this is the OAuth posting path. Reuses that
module's ``classify_access_error`` + ``gsc_service._extract_status_code`` for
error mapping. Pure ``parse_location`` is unit-tested.

Refs: developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Everything the picker needs about a listing. metadata.placeId links a listing
# back to the Place ID we already store on clients.gbp; phone is a disambiguator
# for the operator (two listings can share a name across cities).
_READ_MASK = "name,title,storefrontAddress,phoneNumbers,metadata"


# ── pure helpers (unit-tested) ───────────────────────────────────────────────
def parse_location(loc: dict, account_id: Optional[str]) -> Optional[dict]:
    """Map a v1 Business Information Location to the picker shape, or None if it
    has no resource name. Pure (unit-tested)."""
    name = (loc or {}).get("name")  # 'locations/{id}'
    if not name:
        return None
    addr = loc.get("storefrontAddress") or {}
    lines = addr.get("addressLines") or []
    locality = addr.get("locality")
    region = addr.get("administrativeArea")
    parts = [*lines]
    if locality:
        parts.append(locality)
    if region:
        parts.append(region)
    address = ", ".join(p for p in parts if p) or None
    phone = (loc.get("phoneNumbers") or {}).get("primaryPhone")
    return {
        "location_id": name,
        "account_id": account_id,
        "title": loc.get("title"),
        "address": address,
        "phone": phone,
        "place_id": (loc.get("metadata") or {}).get("placeId"),
    }


# ── Google client build (OAuth or SA, via gbp_auth) ──────────────────────────
def _build(service_name: str, creds):
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build(service_name, "v1", credentials=creds, cache_discovery=False)


# ── live resolution ──────────────────────────────────────────────────────────
def resolve_connected_locations() -> dict:
    """Every listing the connected account manages, flagged with the client each
    is already registered to. Returns {locations, detail}; detail is set (and
    locations empty) on any failure — the UI shows it instead of a crash."""
    from services import gbp_auth  # lazy — avoids google imports at module load
    from services import gbp_performance_service as perf
    from services import gsc_service

    if not gbp_auth.is_configured():
        return {"locations": [], "detail": "gbp_not_connected"}
    try:
        creds = gbp_auth.credentials()
        accounts_client = _build("mybusinessaccountmanagement", creds)
        info_client = _build("mybusinessbusinessinformation", creds)
    except Exception as exc:  # noqa: BLE001 — missing libs / bad creds
        logger.error("gbp_locations.client_build_failed", extra={"error": str(exc)})
        return {"locations": [], "detail": "client_build_failed"}

    try:
        acct_resp = accounts_client.accounts().list().execute()
    except Exception as exc:  # noqa: BLE001
        code = gsc_service._extract_status_code(exc)
        logger.info("gbp_locations.accounts_list_failed", extra={"status_code": code})
        return {"locations": [], "detail": perf.classify_access_error(code).detail or "accounts_list_failed"}

    resolved: list[dict] = []
    for acct in acct_resp.get("accounts", []) or []:
        account_id = acct.get("name")  # 'accounts/{id}'
        if not account_id:
            continue
        try:
            page_token = None
            while True:
                loc_resp = (
                    info_client.accounts().locations()
                    .list(parent=account_id, readMask=_READ_MASK,
                          pageSize=100, pageToken=page_token)
                    .execute()
                )
                for loc in loc_resp.get("locations", []) or []:
                    parsed = parse_location(loc, account_id)
                    if parsed:
                        resolved.append(parsed)
                page_token = loc_resp.get("nextPageToken")
                if not page_token:
                    break
        except Exception as exc:  # noqa: BLE001 — one account failing must not abort the rest
            logger.info("gbp_locations.locations_list_failed",
                        extra={"account_id": account_id, "status_code": gsc_service._extract_status_code(exc)})
            continue

    _annotate_registered(resolved)
    return {"locations": resolved, "detail": None if resolved else "no_locations_visible"}


def _annotate_registered(locations: list[dict]) -> None:
    """Tag each resolved listing with the client it's already registered to (by
    location_id), so the operator doesn't double-assign. In-place, best-effort."""
    if not locations:
        return
    loc_ids = [l["location_id"] for l in locations if l.get("location_id")]
    try:
        rows = (
            get_supabase().table("gbp_locations")
            .select("location_id, client_id, clients(name)")
            .in_("location_id", loc_ids).execute().data or []
        )
    except Exception as exc:  # noqa: BLE001 — a join hiccup shouldn't blank the picker
        logger.info("gbp_locations.registered_lookup_failed", extra={"error": str(exc)})
        return
    by_loc = {r["location_id"]: r for r in rows}
    for loc in locations:
        reg = by_loc.get(loc.get("location_id"))
        if reg:
            loc["registered_client_id"] = reg.get("client_id")
            loc["registered_client_name"] = (reg.get("clients") or {}).get("name")


# ── registration ─────────────────────────────────────────────────────────────
def register_location(
    client_id: str, location_id: str, account_id: Optional[str],
    place_id: Optional[str], title: Optional[str], user_id: Optional[str],
) -> dict:
    """Assign a resolved listing to a client (upsert, access_status='ok') so it
    appears in the Compose picker. Idempotent on (client_id, location_id)."""
    loc = (location_id or "").strip()
    if not loc:
        raise HTTPException(status_code=400, detail="location_id_required")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id_required")  # v4 posts need account+location
    row = {
        "client_id": client_id,
        "location_id": loc,
        "account_id": account_id,
        "place_id": place_id,
        "title": title,
        "access_status": "ok",
        "last_verified_at": "now()",
        "created_by": user_id,
        "updated_at": "now()",
    }
    res = (
        get_supabase().table("gbp_locations")
        .upsert(row, on_conflict="client_id,location_id")
        .execute()
    )
    logger.info("gbp_locations.registered",
                extra={"client_id": client_id, "location_id": loc})
    return res.data[0]


def unregister_location(client_id: str, row_id: str) -> None:
    """Remove a registered location row (its posts cascade-delete)."""
    res = (
        get_supabase().table("gbp_locations").delete()
        .eq("id", row_id).eq("client_id", client_id).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="gbp_location_not_found")
