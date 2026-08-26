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
import math
import re
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Everything the picker needs about a listing. metadata.placeId links a listing
# back to the Place ID we already store on clients.gbp; latlng disambiguates two
# same-name listings across cities (e.g. WheelHouse IT FL vs Orlando); phone is a
# human-legible disambiguator.
_READ_MASK = "name,title,storefrontAddress,phoneNumbers,latlng,metadata"

# Company-suffix / stopword noise stripped before matching a client's business
# name against a listing title.
_NAME_STOP = {
    "the", "llc", "inc", "co", "ltd", "corp", "company", "services", "service",
    "and", "&", "of", "a",
}
# A match this strong (name + geo) is auto-confidently the client's listing.
_CONFIDENT = 0.55


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
    latlng = loc.get("latlng") or {}
    meta = loc.get("metadata") or {}
    return {
        "location_id": name,
        "account_id": account_id,
        "title": loc.get("title"),
        "address": address,
        "phone": phone,
        "lat": latlng.get("latitude"),
        "lng": latlng.get("longitude"),
        "place_id": meta.get("placeId"),
        "maps_uri": meta.get("mapsUri"),  # carries the CID — the exact-match key
    }


def parse_cid(uri: Optional[str]) -> Optional[str]:
    """Extract the Google **CID** (the listing's stable numeric id) from a Maps
    URL, as a decimal string. Handles both forms the suite sees:
      * the stored `clients.gbp.google_maps_uri` hex form ``…!1s0x..:0x<hex>`` →
        the second hex is the CID (converted from hex);
      * the Business Information API's ``metadata.mapsUri`` ``?cid=<decimal>`` form.
    Pure; None when no CID is present. The CID is the identifier both the client
    dashboard and the API listing share, so it pins the match to the *same*
    business the dashboard shows (immune to name/geo lookalikes)."""
    if not uri:
        return None
    m = re.search(r"[?&]cid=(\d+)", uri)
    if m:
        return m.group(1)
    m = re.search(r"0x[0-9a-fA-F]+:0x([0-9a-fA-F]+)", uri)
    if m:
        try:
            return str(int(m.group(1), 16))
        except ValueError:
            return None
    return None


def find_exact_match(
    client_cid: Optional[str], client_place_id: Optional[str], locations: list[dict]
) -> Optional[dict]:
    """The listing that *is* the client's dashboard GBP, by exact identifier
    (Place ID, else CID) — not similarity. None when no exact key matches. Pure."""
    if client_place_id:
        for loc in locations:
            if loc.get("place_id") and loc["place_id"] == client_place_id:
                return loc
    if client_cid:
        for loc in locations:
            if parse_cid(loc.get("maps_uri")) == client_cid:
                return loc
    return None


def _name_tokens(value: Optional[str]) -> set[str]:
    """Lowercased alnum tokens of a business name, minus company-suffix noise."""
    toks = re.findall(r"[a-z0-9]+", (value or "").lower())
    return {t for t in toks if t not in _NAME_STOP}


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Jaccard overlap of two business names' significant tokens (0..1). Pure."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_latlng_from_maps_uri(uri: Optional[str]) -> Optional[tuple[float, float]]:
    """Pull (lat, lng) out of a stored Google Maps place URL. Prefers the precise
    ``!3d<lat>!4d<lng>`` pin, falling back to the ``@lat,lng`` viewport centre.
    Pure; None when neither is present."""
    if not uri:
        return None
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", uri)
    if not m:
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", uri)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except (TypeError, ValueError):
        return None


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lng) points. Pure."""
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _geo_score(client_ll: Optional[tuple[float, float]], loc: dict) -> Optional[float]:
    """0..1 proximity score of a listing to the client's pin, or None when either
    side lacks coordinates. Tight bands — geo is the multi-location tiebreaker."""
    if not client_ll or loc.get("lat") is None or loc.get("lng") is None:
        return None
    dist = _haversine_km(client_ll, (loc["lat"], loc["lng"]))
    if dist <= 0.3:
        return 1.0
    if dist <= 1.0:
        return 0.8
    if dist <= 3.0:
        return 0.5
    if dist <= 10.0:
        return 0.2
    return 0.0


def score_match(client_name: Optional[str], client_ll: Optional[tuple[float, float]], loc: dict) -> float:
    """Combined 0..1 confidence that ``loc`` is this client's listing. Name always
    counts; geo (when both sides have coords) is weighted in as the disambiguator
    for same-name listings in different cities. Pure (unit-tested)."""
    name = name_similarity(client_name, loc.get("title"))
    geo = _geo_score(client_ll, loc)
    if geo is None:
        return round(name, 4)
    return round(name * 0.6 + geo * 0.4, 4)


def rank_matches(client_name: Optional[str], client_ll: Optional[tuple[float, float]], locations: list[dict]) -> list[dict]:
    """Return the listings scored + sorted best-first (each gets a ``score``).
    Pure — the live resolution feeds it, the frontend renders the top as the
    client's suggested profile with the rest as a fallback."""
    scored = [{**loc, "score": score_match(client_name, client_ll, loc)} for loc in locations]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


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


def match_client_location(client_id: str) -> dict:
    """Resolve the *one* listing that is this client's Google Business Profile.

    Uses what the suite already knows about the client (its captured GBP business
    name + Maps pin) to auto-match against the connected account's managed
    listings — so the operator confirms a single card, not a browse. Returns
    ``{client_label, matched, candidates, detail}``: ``matched`` is the confident
    pick (score ≥ threshold) else None; ``candidates`` is every listing ranked, the
    fallback when the match isn't confident. Best-effort — never raises."""
    try:
        rows = (
            get_supabase().table("clients")
            .select("name, gbp").eq("id", client_id).limit(1).execute().data or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_locations.client_load_failed", extra={"error": str(exc)})
        rows = []
    client = rows[0] if rows else {}
    gbp = client.get("gbp") or {}
    client_name = gbp.get("business_name") or client.get("name")
    client_ll = parse_latlng_from_maps_uri(gbp.get("google_maps_uri"))
    client_cid = parse_cid(gbp.get("google_maps_uri"))
    client_place_id = gbp.get("place_id")
    client_label = client_name

    resolved = resolve_connected_locations()
    if resolved.get("detail") and not resolved.get("locations"):
        return {"client_label": client_label, "matched": None, "candidates": [], "detail": resolved["detail"]}

    locations = resolved.get("locations") or []
    ranked = rank_matches(client_name, client_ll, locations)

    # Exact identity (Place ID / CID) is the dashboard's GBP — always wins over
    # name/geo similarity, and is hoisted to the front as the confident match.
    exact = find_exact_match(client_cid, client_place_id, locations)
    if exact:
        matched = {**exact, "score": 1.0}
        ranked = [matched] + [l for l in ranked if l.get("location_id") != exact.get("location_id")]
    else:
        top = ranked[0] if ranked else None
        matched = top if (top and top.get("score", 0) >= _CONFIDENT) else None

    return {
        "client_label": client_label,
        "matched": matched,
        "candidates": ranked,
        "detail": None if ranked else "no_locations_visible",
    }


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


# ── bulk onboarding ──────────────────────────────────────────────────────────
def _client_gbp_identity(client: dict) -> dict:
    """Everything the matchers need about a client's captured GBP. ``place_id`` is
    read from the top-level ``gbp_place_id`` column first (the JSONB ``gbp.place_id``
    is often absent), then the JSONB — either exact key pins the match."""
    gbp = client.get("gbp") or {}
    return {
        "name": gbp.get("business_name") or client.get("name"),
        "latlng": parse_latlng_from_maps_uri(gbp.get("google_maps_uri")),
        "cid": parse_cid(gbp.get("google_maps_uri")),
        "place_id": client.get("gbp_place_id") or gbp.get("place_id"),
        "has_gbp": bool(gbp.get("business_name") or client.get("gbp_place_id") or gbp.get("place_id")),
    }


def _match_from_resolved(ident: dict, locations: list[dict]) -> Optional[dict]:
    """Pick the one listing that is this client's GBP from an already-resolved set
    — exact identity (Place ID / CID) first, else the top name+geo match if it
    clears the confidence bar. Pure. None when nothing is confident."""
    exact = find_exact_match(ident["cid"], ident["place_id"], locations)
    if exact:
        return {**exact, "score": 1.0}
    ranked = rank_matches(ident["name"], ident["latlng"], locations)
    top = ranked[0] if ranked else None
    return top if (top and top.get("score", 0) >= _CONFIDENT) else None


def _enqueue_backfill(supabase, location_row_id: str) -> None:
    """Queue a ~18-month historical metrics pull for a freshly registered location."""
    end = date.today()
    start = end - timedelta(days=settings.gbp_metrics_backfill_days)
    supabase.table("async_jobs").insert(
        {
            "job_type": "gbp_metrics_ingest",
            "entity_id": str(location_row_id),
            "payload": {
                "location_row_id": str(location_row_id),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        }
    ).execute()


def onboard_eligible_clients(user_id: Optional[str] = None) -> dict:
    """Auto-register every client that has a captured GBP but no ``gbp_locations``
    row, matching against the connected account's managed listings, and kick off a
    backfill for each. Resolves the listing set ONCE (one Google round-trip), then
    matches with the pure helpers. Best-effort per client — one failure is recorded
    and skipped, never aborts the batch.

    Returns ``{resolved, onboarded:[…], skipped:[{name, reason}], detail}``.
    """
    supabase = get_supabase()
    resolved = resolve_connected_locations()
    locations = resolved.get("locations") or []
    if not locations:
        return {
            "resolved": 0, "onboarded": [], "skipped": [],
            "detail": resolved.get("detail") or "no_locations_visible",
        }

    try:
        clients = (
            supabase.table("clients").select("id, name, gbp, gbp_place_id").execute().data or []
        )
        reg = supabase.table("gbp_locations").select("client_id, location_id").execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.error("gbp_onboard.load_failed", extra={"error": str(exc)})
        return {"resolved": len(locations), "onboarded": [], "skipped": [], "detail": "load_failed"}

    registered_clients = {r["client_id"] for r in reg}
    used_location_ids = {r["location_id"] for r in reg}  # a listing already assigned to someone

    onboarded: list[dict] = []
    skipped: list[dict] = []
    for c in clients:
        cid = c["id"]
        if cid in registered_clients:
            continue
        ident = _client_gbp_identity(c)
        if not ident["has_gbp"]:
            continue  # client has no captured GBP — nothing to onboard
        matched = _match_from_resolved(ident, locations)
        if not matched:
            skipped.append({"client_id": cid, "name": c.get("name"), "reason": "no_confident_match"})
            continue
        loc_id = matched.get("location_id")
        if loc_id in used_location_ids or matched.get("registered_client_id"):
            skipped.append({"client_id": cid, "name": c.get("name"), "reason": "listing_already_assigned"})
            continue
        try:
            row = register_location(
                cid, loc_id, matched.get("account_id"),
                matched.get("place_id") or ident["place_id"],
                matched.get("title") or ident["name"], user_id,
            )
            _enqueue_backfill(supabase, row["id"])
        except Exception as exc:  # noqa: BLE001 — one client's failure isn't the batch's
            logger.error("gbp_onboard.register_failed", extra={"client_id": cid, "error": str(exc)})
            skipped.append({"client_id": cid, "name": c.get("name"), "reason": "register_failed"})
            continue
        used_location_ids.add(loc_id)
        onboarded.append(
            {"client_id": cid, "name": c.get("name"), "location_id": loc_id,
             "title": matched.get("title"), "score": matched.get("score")}
        )

    return {"resolved": len(locations), "onboarded": onboarded, "skipped": skipped, "detail": None}


async def run_gbp_onboard_job(job: dict) -> None:
    """async_jobs handler for job_type='gbp_onboard' — bulk-onboard eligible clients."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = onboard_eligible_clients(user_id=payload.get("user_id"))
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("gbp_onboard.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:1000], "completed_at": "now()"}
        ).eq("id", job_id).execute()
