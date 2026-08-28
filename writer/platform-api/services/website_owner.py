"""Website Builder — a site's own business identity when there is no client.

A rank-and-rent or PBN site is not a client's website; it is an agency-owned
property with its own business identity — a name, a brand voice, a service area.
That identity is exactly what every generator already needs, so rather than tear
the client requirement out of the shared nlp/blog pipeline (which also writes
Local SEO, Ecommerce and Blog), a property is stored as a lightweight `clients`
row with `kind='owned_property'`:

* it is the same shape every generator reads, so generation, freeze, publish and
  notifications work unchanged; and
* `kind` keeps it out of client-facing surfaces (the fleet view badges it, the
  clients list filters it out) — it is a property, not a customer.

This is the locked owner ruling (2026-07-17, stated in migrations
`20260803190000` / `20260803210000`): every site belongs to a client; a
standalone informational/property site gets a lightweight client row. The `kind`
column, its index, the fleet badge and the portfolio-conflict logic were all
pre-built for exactly this. What was missing — and what this module adds — is the
path that mints one, and the surface that edits its brand voice from inside the
website workspace (a property has no client screen to edit it on).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

OWNED_PROPERTY = "owned_property"


class OwnerError(Exception):
    """Stable error code, not prose (with the HTTP status the router should use)."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def build_property_row(
    *,
    name: str,
    website_url: Optional[str] = None,
    brand_voice_text: Optional[str] = None,
    icp_text: Optional[str] = None,
    business_location: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """The `clients` insert for a new owned property (pure).

    `website_analysis_status` is 'pending' only when there is a URL to analyze —
    a property created from a typed guide alone has nothing to scan, and leaving
    it 'pending' (the column default) would imply a scrape that never runs. Brand
    voice / ICP typed at creation are converged to the canonical `brand_voice` /
    `detected_icp` shape (source:'user'), exactly as the clients-create path does,
    so generation can read them immediately.
    """
    from services import brand_voice_service, icp_service

    row: dict = {
        "name": (name or "").strip(),
        "kind": OWNED_PROPERTY,
        "created_by": user_id or None,
    }
    url = (website_url or "").strip()
    row["website_url"] = url or None
    # 'complete' (not the 'pending' default) when there is nothing to analyze, so
    # a guide-only property is never stuck awaiting a scan that will not happen.
    row["website_analysis_status"] = "pending" if url else "complete"

    brand_voice = brand_voice_service.merge_raw_text(None, brand_voice_text or None)
    if brand_voice is not None:
        row["brand_voice"] = brand_voice
    detected_icp = icp_service.merge_raw_text(None, icp_text or None)
    if detected_icp is not None:
        row["detected_icp"] = detected_icp

    loc = (business_location or "").strip()
    if loc:
        row["business_location"] = loc
    return row


def _name_candidates(name: str, disambiguator: Optional[str]) -> list[str]:
    """Names to try, in order, so a property whose business name collides with an
    existing client (or another property) still gets created.

    `clients.name` is globally unique, but two rank-and-rent sites can legitimately
    share a business name across cities. The clean public name lives on
    `config.business.name` (which generation prefers), so the internal handle can
    carry a disambiguator without polluting the content.
    """
    base = (name or "").strip() or "Property"
    out = [base]
    dis = (disambiguator or "").strip()
    if dis:
        out.append(f"{base} ({dis})")
    out.append(f"{base} ({uuid.uuid4().hex[:8]})")
    return out


def create_property_client(
    *,
    name: str,
    website_url: Optional[str] = None,
    brand_voice_text: Optional[str] = None,
    icp_text: Optional[str] = None,
    business_location: Optional[str] = None,
    disambiguator: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """Mint the lightweight `owned_property` client backing a standalone site.

    Retries the insert under a disambiguated internal name on a unique-name
    collision (see `_name_candidates`). Best-effort auto-scans brand voice + ICP
    from the site URL, exactly like the clients-create path — a guide-only
    property simply skips the scan.
    """
    supabase = get_supabase()
    base_row = build_property_row(
        name=name,
        website_url=website_url,
        brand_voice_text=brand_voice_text,
        icp_text=icp_text,
        business_location=business_location,
        user_id=user_id,
    )

    client: Optional[dict] = None
    last_exc: Optional[Exception] = None
    for candidate in _name_candidates(name, disambiguator):
        try:
            client = (
                supabase.table("clients")
                .insert({**base_row, "name": candidate})
                .execute()
            ).data[0]
            break
        except Exception as exc:  # noqa: BLE001 — only a name collision is retryable
            last_exc = exc
            if "name" in str(exc).lower() and (
                "duplicate" in str(exc).lower() or "unique" in str(exc).lower()
            ):
                continue
            raise
    if client is None:
        raise OwnerError("property_create_failed", 500) from last_exc

    _enqueue_auto_assets(client, user_id or "")
    logger.info(
        "website_owner.property_created",
        extra={"client_id": client["id"], "name": client.get("name")},
    )
    return client


def _enqueue_auto_assets(client: dict, user_id: str) -> None:
    """Auto-generate the property's brand voice + ICP from its URL (best-effort).

    Mirrors `clients._enqueue_auto_brand_voice_icp`: skipped when disabled or when
    there is nothing to analyze (no website URL). The scans never override the
    user's typed guide — they enrich it — so running this alongside a typed
    brand_voice is safe.
    """
    if not settings.auto_generate_brand_voice_icp:
        return
    if not client.get("website_url"):
        return
    get_supabase().table("async_jobs").insert(
        [
            {
                "job_type": job_type,
                "entity_id": client["id"],
                "payload": {"client_id": client["id"], "user_id": user_id},
            }
            for job_type in ("brand_voice_scan", "icp_scan")
        ]
    ).execute()


# --------------------------------------------------------------------------
# Brand voice, edited from inside the website workspace (properties only)
# --------------------------------------------------------------------------


def _load(website_id: str) -> tuple[dict, dict]:
    supabase = get_supabase()
    sites = (
        supabase.table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not sites:
        raise OwnerError("website_not_found", 404)
    website = sites[0]
    client = (
        supabase.table("clients")
        .select("*")
        .eq("id", website["client_id"])
        .limit(1)
        .execute()
    ).data
    return website, (client[0] if client else {})


def _raw_text(blob: Optional[dict]) -> str:
    return ((blob or {}).get("raw_text") or "").strip()


def get_brand(website_id: str) -> dict:
    """The site's brand voice / ICP guide text, plus whether it is editable here.

    `editable` is True only for an `owned_property` backing row — a real client's
    voice is edited on the client screen, never silently from a site. `has_context`
    tells the UI whether generation is currently unblocked.
    """
    from services.website_generate import has_brand_context

    website, client = _load(website_id)
    kind = client.get("kind") or "client"
    return {
        "editable": kind == OWNED_PROPERTY,
        "kind": kind,
        "brand_voice": _raw_text(client.get("brand_voice")),
        "icp": _raw_text(client.get("detected_icp")),
        "has_context": has_brand_context(client),
    }


def set_brand(
    website_id: str, *, brand_voice: Optional[str] = None, icp: Optional[str] = None
) -> dict:
    """Update a property's brand voice / ICP guide from the website workspace.

    Refused for a real client (edit those on the client screen). Only the fields
    that were sent are written, so the tab can save the voice without disturbing
    the ICP.
    """
    from services import brand_voice_service, icp_service

    website, client = _load(website_id)
    if (client.get("kind") or "client") != OWNED_PROPERTY:
        raise OwnerError("not_a_property", 409)

    patch: dict = {}
    if brand_voice is not None:
        merged = brand_voice_service.merge_raw_text(client.get("brand_voice"), brand_voice)
        patch["brand_voice"] = merged
    if icp is not None:
        merged_icp = icp_service.merge_raw_text(client.get("detected_icp"), icp)
        patch["detected_icp"] = merged_icp
    if not patch:
        return get_brand(website_id)

    patch["updated_at"] = "now()"
    get_supabase().table("clients").update(patch).eq("id", client["id"]).execute()
    logger.info(
        "website_owner.brand_updated",
        extra={"client_id": client["id"], "fields": sorted(patch.keys())},
    )
    return get_brand(website_id)
