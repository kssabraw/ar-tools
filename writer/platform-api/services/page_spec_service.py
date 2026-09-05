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
from db.supabase_client import get_supabase

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


# ── per-client length report (plan §5.6) ────────────────────────────────────

def summarize_lengths(rows: list[dict[str, Any]], recent: int = 10) -> dict[str, Any]:
    """Pure: target-vs-actual rollup over a client's page rows so drift shows
    up in a table, not in the owner's review of a client's pages."""
    with_spec = [r for r in rows if r.get("target_words") and r.get("actual_words") is not None]
    counts = {"in_band": 0, "over_length": 0, "under_length": 0}
    overages: list[float] = []
    for r in with_spec:
        st = r.get("length_status") or "in_band"
        counts[st] = counts.get(st, 0) + 1
        t, a = int(r["target_words"]), int(r["actual_words"])
        if t > 0:
            overages.append((a - t) / t * 100.0)
    n = len(with_spec)
    structured = [r for r in rows if r.get("structure_status")]
    drift = sum(1 for r in structured if r.get("structure_status") == "drift")
    return {
        "pages": len(rows),
        "with_spec": n,
        "in_band": counts.get("in_band", 0),
        "over_length": counts.get("over_length", 0),
        "under_length": counts.get("under_length", 0),
        "in_band_pct": round(counts.get("in_band", 0) / n * 100.0, 1) if n else None,
        "avg_overage_pct": round(sum(overages) / len(overages), 1) if overages else None,
        # Structure (Phase 4): pages judged, and how many still drift.
        "structure_checked": len(structured),
        "structure_ok": len(structured) - drift,
        "structure_drift": drift,
        "recent": [
            {"id": r.get("id"), "keyword": r.get("keyword"), "target_words": int(r["target_words"]),
             "actual_words": int(r["actual_words"]), "length_status": r.get("length_status") or "in_band",
             "structure_status": r.get("structure_status"), "created_at": r.get("created_at")}
            for r in with_spec[:recent]
        ],
    }


def length_report(client_id: str) -> dict[str, Any]:
    res = (
        get_supabase().table("local_seo_pages")
        .select("id, keyword, target_words, actual_words, length_status, structure_status, created_at")
        .eq("client_id", client_id).is_("deleted_at", "null")
        .order("created_at", desc=True).limit(200).execute()
    )
    return summarize_lengths(res.data or [])
