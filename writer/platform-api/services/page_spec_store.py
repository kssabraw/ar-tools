"""Persistence + resolution for Local SEO page specs (plan §6 Phase 1).

`local_seo_page_specs` keeps one versioned spec per client × keyword ×
location (keyed exactly like the SERP analysis cache, so spec and analysis line
up 1:1). The active version is the row with ``superseded_at`` null.

Resolution rule (plan §5.6 — "edits stick"):

- an **edited** active spec is used as-is and never overwritten automatically;
- otherwise a fresh spec is built from the current inputs (pure
  ``page_spec.build_spec``) and, when it differs materially from the active
  one (or there is none), saved as the next version — so a re-analysis that
  moves the SERP target produces a new version, while an identical rebuild
  leaves the history alone.

Everything here is best-effort from the caller's point of view: generation
must never fail because a spec couldn't be loaded or saved.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase
from services import analysis_cache, page_spec

logger = logging.getLogger(__name__)

_TABLE = "local_seo_page_specs"
_ROW_COLUMNS = "id, client_id, spec_key, keyword, location, location_code, version, spec, edited_at, edited_by, superseded_at, created_at"

# Reference page types that may drive a local landing page's layout, in order
# of preference (mirrors local_seo_service.generate_page).
REFERENCE_PAGE_TYPES = ("local_landing", "location")


def spec_key(keyword: str, location_code: Optional[int], location: str) -> str:
    return analysis_cache.cache_key(keyword, location_code, location)


# ── pure helpers ────────────────────────────────────────────────────────────

def _band_signature(spec: dict[str, Any]) -> Any:
    """The parts of a spec that matter for 'is this materially different':
    the page band, the structure caps and each section's key + band + required
    flag. Provenance timestamps and generated_at are deliberately excluded."""
    total = spec.get("total") or {}
    return (
        spec.get("structure_mode") or "template",
        (total.get("min"), total.get("target"), total.get("max"), total.get("basis")),
        tuple(sorted((k, v if not isinstance(v, dict) else tuple(sorted(v.items())))
                     for k, v in (spec.get("structure") or {}).items())),
        tuple(
            (s.get("key"), s.get("required"), s.get("min_words"), s.get("max_words"))
            for s in spec.get("sections") or []
        ),
    )


def materially_different(a: Optional[dict[str, Any]], b: Optional[dict[str, Any]]) -> bool:
    """Pure: whether two specs differ on anything the writer would act on."""
    if a is None or b is None:
        return a is not b
    return _band_signature(a) != _band_signature(b)


def pick_reference(page_structures: Optional[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """The first USABLE reference among the preferred page types; when none is
    usable, the first present one (so the spec's provenance records why it was
    rejected). Pure."""
    structures = page_structures or {}
    first_present: tuple[Optional[dict[str, Any]], Optional[str]] = (None, None)
    for page_type in REFERENCE_PAGE_TYPES:
        entry = structures.get(page_type)
        if not isinstance(entry, dict):
            continue
        if first_present[0] is None:
            first_present = (entry, page_type)
        usable, _ = page_spec.reference_usable(entry)
        if usable:
            return entry, page_type
    return first_present


def public_spec(row: dict[str, Any]) -> dict[str, Any]:
    """The spec JSON as handed to the writer / the API: the stored document plus
    its row identity (`id`, `version`, `edited_at`) so a page can record which
    version it was written against."""
    spec = copy.deepcopy(row.get("spec") or {})
    spec["id"] = row.get("id")
    spec["version"] = row.get("version")
    spec["edited_at"] = row.get("edited_at")
    return spec


# ── I/O ─────────────────────────────────────────────────────────────────────

def get_active(client_id: str, key: str) -> Optional[dict[str, Any]]:
    res = (
        get_supabase().table(_TABLE).select(_ROW_COLUMNS)
        .eq("client_id", client_id).eq("spec_key", key)
        .is_("superseded_at", "null")
        .order("version", desc=True).limit(1).execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def get_by_id(spec_id: str) -> Optional[dict[str, Any]]:
    res = get_supabase().table(_TABLE).select(_ROW_COLUMNS).eq("id", spec_id).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def list_versions(client_id: str, key: str, limit: int = 20) -> list[dict[str, Any]]:
    res = (
        get_supabase().table(_TABLE)
        .select("id, version, edited_at, edited_by, superseded_at, created_at")
        .eq("client_id", client_id).eq("spec_key", key)
        .order("version", desc=True).limit(limit).execute()
    )
    return res.data or []


def save_new_version(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    spec: dict[str, Any],
    *,
    edited_by: Optional[str] = None,
    edited: bool = False,
    previous: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Insert the next version and supersede the previous active row."""
    key = spec_key(keyword, location_code, location)
    now = datetime.now(timezone.utc).isoformat()
    prev = previous if previous is not None else get_active(client_id, key)
    version = int((prev or {}).get("version") or 0) + 1
    stored = copy.deepcopy(spec)
    for k in ("id", "version"):
        stored.pop(k, None)
    stored["edited_at"] = now if edited else None
    row = {
        "client_id": client_id,
        "spec_key": key,
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "version": version,
        "spec": stored,
        "edited_at": now if edited else None,
        "edited_by": edited_by if edited else None,
    }
    inserted = get_supabase().table(_TABLE).insert(row).execute().data[0]
    if prev:
        get_supabase().table(_TABLE).update({"superseded_at": now}).eq("id", prev["id"]).execute()
    logger.info(
        "page_spec.saved",
        extra={"client_id": client_id, "spec_key": key, "version": version, "edited": edited},
    )
    return inserted


def client_has_reviews(client: dict[str, Any]) -> bool:
    """Whether the client has review text on file (``clients.gbp.reviews`` —
    the only review source the writer is handed). Pure."""
    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else {}
    reviews = gbp.get("reviews")
    return isinstance(reviews, list) and any(isinstance(r, dict) and (r.get("text") or "").strip() for r in reviews)


def client_structure_overrides() -> bool:
    """Whether a usable client reference layout IS the page structure (config
    ``local_seo_client_structure_overrides``, default on)."""
    try:
        from config import settings  # lazy: keep the pure helpers importable alone

        return bool(getattr(settings, "local_seo_client_structure_overrides", True))
    except Exception:  # noqa: BLE001
        return True


def resolve_spec(
    client: dict[str, Any],
    keyword: str,
    location: str,
    location_code: Optional[int],
    serp_analysis: Optional[dict[str, Any]],
    fallback_target: Optional[int],
    *,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """The active spec for this client × keyword × location, building and
    saving a new version when needed (see the module docstring). Returns the
    public spec (with `id` / `version`). Raises on I/O failure — callers that
    must not fail wrap it."""
    client_id = str(client["id"])
    key = spec_key(keyword, location_code, location)
    active = None if force_rebuild else get_active(client_id, key)
    if active and active.get("edited_at"):
        return public_spec(active)
    reference, ref_type = pick_reference(client.get("page_structures"))
    fresh = page_spec.build_spec(
        client_id=client_id, keyword=keyword, location=location, location_code=location_code,
        serp_analysis=serp_analysis, reference_entry=reference, reference_page_type=ref_type,
        fallback_target=fallback_target,
        client_structure_overrides=client_structure_overrides(),
        has_reviews=client_has_reviews(client),
    )
    if active and not materially_different(active.get("spec"), fresh):
        return public_spec(active)
    saved = save_new_version(client_id, keyword, location, location_code, fresh, previous=active)
    return public_spec(saved)


def save_edit(
    client: dict[str, Any],
    keyword: str,
    location: str,
    location_code: Optional[int],
    spec: dict[str, Any],
    user_id: Optional[str],
) -> tuple[dict[str, Any], list[str]]:
    """Persist a hand-edited spec as the next (edited) version after validating
    it. Returns ``(public_spec, validation_errors)``; an invalid spec is NOT
    saved and the errors are returned instead."""
    errors = page_spec.validate_spec(spec)
    if errors:
        return spec, errors
    cleaned = copy.deepcopy(spec)
    cleaned["client_id"] = str(client["id"])
    cleaned["keyword"] = keyword
    cleaned["location"] = location
    cleaned["location_code"] = location_code
    cleaned["validation_errors"] = []
    saved = save_new_version(
        str(client["id"]), keyword, location, location_code, cleaned, edited_by=user_id, edited=True
    )
    return public_spec(saved), []
