"""Route-facing page-spec operations (plan §6 Phase 1): read-or-build, edit,
rebuild, download. Thin orchestration over `page_spec_store` (persistence) and
`page_spec` (the pure core); the SERP analysis is only ever read from the cache
here — a spec read must never spend a paid call."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import HTTPException
from fastapi.responses import Response

from services import analysis_cache, locations_service, page_spec_store

logger = logging.getLogger(__name__)


def _client(client_id: str) -> dict[str, Any]:
    from services.local_seo_service import _get_client  # lazy: avoid a module cycle

    return _get_client(client_id)


async def _resolve_location(client: dict[str, Any], location: str, location_code: Optional[int]) -> tuple[str, Optional[int]]:
    return await locations_service.resolve_location(client, location, location_code)


def _fallback_target(location_code: Optional[int], location: str) -> int:
    from services.local_seo_service import _resolve_fallback_length_target  # lazy

    return _resolve_fallback_length_target(location_code, location)


def _envelope(client_id: str, keyword: str, location: str, location_code: Optional[int], spec: dict[str, Any]) -> dict[str, Any]:
    key = page_spec_store.spec_key(keyword, location_code, location)
    return {
        "spec": spec,
        "id": spec.get("id"),
        "version": spec.get("version"),
        "edited_at": spec.get("edited_at"),
        "validation_errors": spec.get("validation_errors") or [],
        "versions": page_spec_store.list_versions(client_id, key),
    }


async def get_or_build(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    *,
    user_id: Optional[str] = None,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    client = _client(client_id)
    location, location_code = await _resolve_location(client, location, location_code)
    serp = analysis_cache.get(keyword, location_code, location)  # cache only — no paid call
    fallback = _fallback_target(location_code, location)
    spec = page_spec_store.resolve_spec(
        client, keyword, location, location_code, serp, fallback, force_rebuild=force_rebuild,
    )
    return _envelope(client_id, keyword, location, location_code, spec)


async def save_edit(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    spec: dict[str, Any],
    *,
    user_id: Optional[str],
) -> dict[str, Any]:
    client = _client(client_id)
    location, location_code = await _resolve_location(client, location, location_code)
    saved, errors = page_spec_store.save_edit(client, keyword, location, location_code, spec, user_id)
    if errors:
        raise HTTPException(status_code=400, detail="page_spec_invalid: " + " | ".join(errors))
    return _envelope(client_id, keyword, location, location_code, saved)


def download(spec_id: str) -> Response:
    row = page_spec_store.get_by_id(spec_id)
    if not row:
        raise HTTPException(status_code=404, detail="page_spec_not_found")
    spec = page_spec_store.public_spec(row)
    slug = "-".join(part for part in (row.get("keyword") or "spec").lower().split())[:60]
    body = json.dumps(spec, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="page-spec-{slug}-v{row.get("version")}.json"'},
    )
