"""Brand Guide Generator router (Phase 4 — the module's first HTTP surface).

Generate on-demand, list/read history, download either render profile (§4.7),
apply structured-field edits (§9 — sets `edited`), adopt a detected logo (§12 Q1),
approve a regulated guide out of `awaiting_signoff` → render (§5.3b), and read the
suggest-only voice surface (§4.8). Reads are `require_auth`; every mutation is
`require_staff` (staff or admin) — the suite has no per-client owner column, so the
§5.3b "admin OR the client's owning staff member" approver collapses to the staff
tier, matching the sibling GBP Profile Editor's apply gate. Generation is gated on
`brand_guide_enabled` (503 while dark); reads/history work regardless so the page
can render its disabled state.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from models.brand_guide import (
    BrandGuide,
    BrandGuideDownload,
    BrandGuideEditRequest,
    BrandGuideStatus,
    GenerateBrandGuideRequest,
    LogoAdoptRequest,
    LogoAdoptResponse,
    VoiceSuggestionResponse,
)
from services import brand_guide, brand_guide_edit, brand_guide_render

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brand-guide"])

_LOGO_BUCKET = "client-logos"
_LOGO_MAX_BYTES = 5 * 1024 * 1024
_LOGO_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg"}


def _resign(guide: dict) -> dict:
    """Re-sign the (expiring) PDF URLs on read so a stale link never 404s."""
    from services.client_report import _signed_url

    if guide.get("storage_path"):
        fresh = _signed_url(guide["storage_path"])
        if fresh:
            guide["pdf_url"] = fresh
    renders = guide.get("renders")
    if isinstance(renders, dict):
        for entry in renders.values():
            if isinstance(entry, dict) and entry.get("storage_path"):
                fresh = _signed_url(entry["storage_path"])
                if fresh:
                    entry["pdf_url"] = fresh
    return guide


def _load_guide(client_id: str, guide_id: str) -> dict:
    rows = (
        get_supabase().table("brand_guides").select("*")
        .eq("id", guide_id).eq("client_id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return rows[0]


# ── status ───────────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand-guide/status", response_model=BrandGuideStatus)
async def brand_guide_status(client_id: UUID, auth: dict = Depends(require_auth)) -> BrandGuideStatus:
    """Whether the module is enabled (the page renders a dark state when off)."""
    return BrandGuideStatus(enabled=bool(settings.brand_guide_enabled))


# ── generate ─────────────────────────────────────────────────────────────────
@router.post("/clients/{client_id}/brand-guide/generate", response_model=BrandGuide)
async def generate_guide(
    client_id: UUID, body: GenerateBrandGuideRequest, auth: dict = Depends(require_staff)
) -> BrandGuide:
    """Enqueue a guide build (capture → extract → vibe → synth → render). Returns
    the queued row; poll the list/detail endpoints while it runs."""
    if not settings.brand_guide_enabled:
        raise HTTPException(status_code=503, detail="brand_guide_not_enabled")
    guide_id = brand_guide.enqueue_brand_guide_generate(
        str(client_id),
        source_url=body.source_url if body.source_url is not None else None,
        pages=body.pages,
        user_id=auth["user_id"],
    )
    return BrandGuide(**_load_guide(str(client_id), guide_id))


# ── list + detail ────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand-guide", response_model=list[BrandGuide])
async def list_guides(client_id: UUID, auth: dict = Depends(require_auth)) -> list[BrandGuide]:
    rows = (
        get_supabase().table("brand_guides").select("*")
        .eq("client_id", str(client_id)).order("version", desc=True).limit(50).execute()
    ).data or []
    return [BrandGuide(**r) for r in rows]


@router.get("/clients/{client_id}/brand-guide/{guide_id}", response_model=BrandGuide)
async def get_guide(
    client_id: UUID, guide_id: UUID, auth: dict = Depends(require_auth)
) -> BrandGuide:
    return BrandGuide(**_resign(_load_guide(str(client_id), str(guide_id))))


# ── download (re-signed, by profile — §4.7) ──────────────────────────────────
@router.get("/clients/{client_id}/brand-guide/{guide_id}/download", response_model=BrandGuideDownload)
async def download_guide(
    client_id: UUID, guide_id: UUID,
    profile: str = Query("client"), auth: dict = Depends(require_auth),
) -> BrandGuideDownload:
    if profile not in brand_guide_edit.PROFILES:
        raise HTTPException(status_code=422, detail="invalid_profile")
    guide = _load_guide(str(client_id), str(guide_id))
    path = brand_guide_edit.resolve_render_path(guide, profile)
    if not path:
        raise HTTPException(status_code=409, detail="not_rendered")
    from services.client_report import _signed_url

    url = _signed_url(path)
    if not url:
        raise HTTPException(status_code=502, detail="signing_failed")
    return BrandGuideDownload(profile=profile, url=url)


# ── structured-field edit (§9 — sets `edited`) ───────────────────────────────
@router.put("/clients/{client_id}/brand-guide/{guide_id}", response_model=BrandGuide)
async def edit_guide(
    client_id: UUID, guide_id: UUID, body: BrandGuideEditRequest,
    auth: dict = Depends(require_staff),
) -> BrandGuide:
    """Apply structured-field edits to the guide's Proposed layer (never the measured
    census). Applying any edit sets `edited=true` so a later regenerate warns/versions
    rather than silently overwriting."""
    guide = _load_guide(str(client_id), str(guide_id))
    try:
        ops = brand_guide_edit.validate_ops([op.model_dump() for op in body.edits])
    except brand_guide_edit.EditError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    new_synth, applied = brand_guide_edit.apply_edits(guide.get("synthesized"), ops)
    if applied == 0:
        raise HTTPException(status_code=409, detail="no_change")
    get_supabase().table("brand_guides").update(
        {"synthesized": new_synth, "edited": True}
    ).eq("id", str(guide_id)).execute()
    return BrandGuide(**_load_guide(str(client_id), str(guide_id)))


# ── logo adopt (§12 Q1) ──────────────────────────────────────────────────────
@router.post("/clients/{client_id}/brand-guide/{guide_id}/logo-adopt", response_model=LogoAdoptResponse)
async def adopt_logo(
    client_id: UUID, guide_id: UUID, body: LogoAdoptRequest,
    auth: dict = Depends(require_staff),
) -> LogoAdoptResponse:
    """Adopt a detected logo candidate → the public client-logos bucket + set
    clients.logo_url. NEVER silently overwrites an existing logo — a client that
    already has logo_url requires an explicit `replace` (PRD §12 Q1)."""
    guide = _load_guide(str(client_id), str(guide_id))
    cand = brand_guide_edit.pick_logo_candidate(guide.get("visual_census"), body.candidate_url)
    if not cand:
        raise HTTPException(status_code=422, detail="unknown_candidate")

    supabase = get_supabase()
    client_rows = supabase.table("clients").select("logo_url").eq("id", str(client_id)).limit(1).execute().data or []
    if not client_rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    existing = (client_rows[0].get("logo_url") or "").strip()
    if existing and not body.replace:
        raise HTTPException(status_code=409, detail="logo_exists")

    public_url = await _rehost_logo(str(body.candidate_url).strip())
    supabase.table("clients").update({"logo_url": public_url}).eq("id", str(client_id)).execute()
    logger.info("brand_guide.logo_adopted",
                extra={"client_id": str(client_id), "guide_id": str(guide_id), "source": cand.get("source")})
    return LogoAdoptResponse(logo_url=public_url)


async def _rehost_logo(url: str) -> str:
    """Download the candidate image and re-host it in the client-logos bucket so the
    adopted logo is a stable suite-owned URL (never a live-host link that can rot)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
            resp = await http.get(url)
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand_guide.logo_fetch_failed", extra={"url": url[:120], "error": str(exc)[:150]})
        raise HTTPException(status_code=502, detail="logo_fetch_failed") from exc

    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = _LOGO_EXT.get(content_type)
    if ext is None:
        raise HTTPException(status_code=422, detail="unsupported_image_type")
    data = resp.content
    if not data:
        raise HTTPException(status_code=422, detail="empty_image")
    if len(data) > _LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="image_too_large")

    supabase = get_supabase()
    path = f"{uuid.uuid4()}.{ext}"
    try:
        supabase.storage.from_(_LOGO_BUCKET).upload(path, data, {"content-type": content_type, "upsert": "true"})
        return supabase.storage.from_(_LOGO_BUCKET).get_public_url(path).rstrip("?")
    except Exception as exc:  # noqa: BLE001
        logger.error("brand_guide.logo_store_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="logo_upload_failed") from exc


# ── regulated sign-off approve → render (§5.3b) ──────────────────────────────
@router.post("/clients/{client_id}/brand-guide/{guide_id}/render-approve", response_model=BrandGuide)
async def approve_render(
    client_id: UUID, guide_id: UUID, auth: dict = Depends(require_staff)
) -> BrandGuide:
    """Approve a regulated guide out of `awaiting_signoff` → enqueue the separate
    `brand_guide_render` job. Only valid for a guide actually in that state."""
    if not settings.brand_guide_enabled:
        raise HTTPException(status_code=503, detail="brand_guide_not_enabled")
    guide = _load_guide(str(client_id), str(guide_id))
    if guide.get("status") != "awaiting_signoff":
        raise HTTPException(status_code=409, detail="not_awaiting_signoff")
    brand_guide_render.enqueue_brand_guide_render(str(client_id), str(guide_id), user_id=auth["user_id"])
    # Reflect the enqueue immediately so the UI flips to "rendering" without a poll gap.
    get_supabase().table("brand_guides").update({"status": "rendering"}).eq("id", str(guide_id)).execute()
    return BrandGuide(**_load_guide(str(client_id), str(guide_id)))


# ── suggest-only voice surface (§4.8) ────────────────────────────────────────
@router.get("/clients/{client_id}/brand-guide/{guide_id}/voice-suggestions", response_model=VoiceSuggestionResponse)
async def voice_suggestions(
    client_id: UUID, guide_id: UUID, auth: dict = Depends(require_auth)
) -> VoiceSuggestionResponse:
    """The refined voice/messaging as copyable text + the Brand Voice editor path.
    Suggest-only (§4.8): applying is the operator's job in the existing editor."""
    guide = _load_guide(str(client_id), str(guide_id))
    text = brand_guide_edit.build_voice_suggestion_text(guide.get("synthesized"))
    return VoiceSuggestionResponse(
        text=text,
        editor_path=f"/clients/{client_id}/brand-voice",
        has_suggestions=bool(text),
    )
