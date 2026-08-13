"""WheelHouse IT location/service page poster router (Wheelhouse-only).

Every route is auth-gated AND client-gated on ``clients.wheelhouse_cpt_enabled``
(a disabled client 404s — the feature is invisible, not merely denied). Content
creation + publishing assert the Freeze Protocol. Generation runs as background
`wheelhouse_generate` jobs (mass runs); one-off generate + publish + dry-run are
synchronous. All WordPress calls happen server-side via the shared publisher.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from middleware.auth import require_auth
from models.wheelhouse import (
    WheelhouseDraftFieldRequest,
    WheelhouseDraftFieldResult,
    WheelhouseGenerateJobResult,
    WheelhouseGenerateOneRequest,
    WheelhouseJobStatus,
    WheelhouseJobsStatusRequest,
    WheelhouseMassJob,
    WheelhouseMassRequest,
    WheelhouseOneOffSaveRequest,
    WheelhousePublishRequest,
)
from services import wheelhouse_service
from services.freeze import assert_not_frozen
from services.wheelhouse_fields import sections
from services.wheelhouse_pages import WordPressPublishError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wheelhouse"])


# ── field schema (drives the one-off form) ───────────────────────────────────

@router.get("/clients/{client_id}/wheelhouse/fields")
async def get_wheelhouse_fields(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The 33-field ACF schema grouped by section (ACF group order) for the form."""
    wheelhouse_service.get_enabled_client(str(client_id))
    return {"sections": sections()}


# ── reads ────────────────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/wheelhouse/pages")
async def list_wheelhouse_pages(
    client_id: UUID,
    deleted: bool = Query(False),
    auth: dict = Depends(require_auth),
) -> dict:
    wheelhouse_service.get_enabled_client(str(client_id))
    return {"pages": wheelhouse_service.list_pages(str(client_id), deleted=deleted)}


@router.get("/clients/{client_id}/wheelhouse/pages/{page_id}")
async def get_wheelhouse_page(
    client_id: UUID, page_id: UUID, auth: dict = Depends(require_auth),
) -> dict:
    wheelhouse_service.get_enabled_client(str(client_id))
    return wheelhouse_service.get_page(str(client_id), str(page_id))


@router.get("/clients/{client_id}/wheelhouse/pages/{page_id}/report")
async def get_wheelhouse_report(
    client_id: UUID, page_id: UUID, auth: dict = Depends(require_auth),
) -> dict:
    wheelhouse_service.get_enabled_client(str(client_id))
    return wheelhouse_service.report_for(wheelhouse_service.get_page(str(client_id), str(page_id)))


# ── generation ───────────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/wheelhouse/generate-mass", response_model=WheelhouseMassJob)
async def generate_mass(
    client_id: UUID, body: WheelhouseMassRequest, auth: dict = Depends(require_auth),
) -> WheelhouseMassJob:
    """Mass Create: enqueue one generation job per city×service."""
    assert_not_frozen(str(client_id))
    job_ids = await wheelhouse_service.enqueue_mass(
        str(client_id), body.state, body.city, body.services, auth["user_id"],
    )
    return WheelhouseMassJob(job_ids=job_ids)


@router.post("/clients/{client_id}/wheelhouse/generate-one")
async def generate_one(
    client_id: UUID, body: WheelhouseGenerateOneRequest, auth: dict = Depends(require_auth),
) -> dict:
    """One-off: synchronously generate all missing fields for a single
    city×service (supplied fields kept verbatim). ``persist=True`` (default) saves
    a draft and returns it; ``persist=False`` returns the fields only (live form
    preview — no Saved row created)."""
    assert_not_frozen(str(client_id))
    if body.persist:
        return await wheelhouse_service.generate_one(
            str(client_id), body.state, body.city, body.service, supplied=body.supplied,
        )
    return await wheelhouse_service.preview_one(
        str(client_id), body.state, body.city, body.service, supplied=body.supplied,
    )


@router.post(
    "/clients/{client_id}/wheelhouse/draft-field",
    response_model=WheelhouseDraftFieldResult,
)
async def draft_field(
    client_id: UUID, body: WheelhouseDraftFieldRequest, auth: dict = Depends(require_auth),
) -> WheelhouseDraftFieldResult:
    """Draft a single ACF field with AI (the one-off form's per-field button)."""
    value = await wheelhouse_service.draft_single_field(
        str(client_id), body.state, body.city, body.service, body.field_name,
    )
    return WheelhouseDraftFieldResult(field_name=body.field_name, value=value)


@router.post("/clients/{client_id}/wheelhouse/one-off")
async def save_one_off(
    client_id: UUID, body: WheelhouseOneOffSaveRequest, auth: dict = Depends(require_auth),
) -> dict:
    """Save a fully user-authored/edited ACF object as a draft (no generation)."""
    assert_not_frozen(str(client_id))
    return wheelhouse_service.save_one_off(
        str(client_id), body.state, body.city, body.service, body.acf,
    )


@router.get(
    "/clients/{client_id}/wheelhouse/generate/{job_id}",
    response_model=WheelhouseGenerateJobResult,
)
async def get_generate_job(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth),
) -> WheelhouseGenerateJobResult:
    wheelhouse_service.get_enabled_client(str(client_id))
    return WheelhouseGenerateJobResult(
        **wheelhouse_service.get_generate_job(str(job_id), str(client_id))
    )


@router.post("/clients/{client_id}/wheelhouse/jobs/status")
async def jobs_status(
    client_id: UUID, body: WheelhouseJobsStatusRequest, auth: dict = Depends(require_auth),
) -> dict:
    wheelhouse_service.get_enabled_client(str(client_id))
    jobs = wheelhouse_service.jobs_status(str(client_id), body.job_ids)
    return {"jobs": [WheelhouseJobStatus(**j).model_dump() for j in jobs]}


# ── publish + dry-run ────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/wheelhouse/pages/{page_id}/dry-run")
async def dry_run(
    client_id: UUID, page_id: UUID, body: WheelhousePublishRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Assemble + resolve the parent chain and return the exact would-POST
    payloads with zero writes."""
    return await wheelhouse_service.dry_run(str(client_id), str(page_id), status=body.status)


@router.post("/clients/{client_id}/wheelhouse/pages/{page_id}/publish")
async def publish(
    client_id: UUID, page_id: UUID, body: WheelhousePublishRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Ensure the State→City chain and upsert the leaf Page with its ACF fields."""
    assert_not_frozen(str(client_id))
    try:
        return await wheelhouse_service.publish(str(client_id), str(page_id), status=body.status)
    except WordPressPublishError as exc:
        # Client-fixable config/transport problems → 422 with the specific code.
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── lifecycle ────────────────────────────────────────────────────────────────

@router.delete("/clients/{client_id}/wheelhouse/pages/{page_id}")
async def delete_page(
    client_id: UUID, page_id: UUID, auth: dict = Depends(require_auth),
) -> dict:
    """Soft-delete → Drafts tab."""
    wheelhouse_service.get_enabled_client(str(client_id))
    wheelhouse_service.soft_delete(str(client_id), str(page_id))
    return {"ok": True}


@router.post("/clients/{client_id}/wheelhouse/pages/{page_id}/restore")
async def restore_page(
    client_id: UUID, page_id: UUID, auth: dict = Depends(require_auth),
) -> dict:
    wheelhouse_service.get_enabled_client(str(client_id))
    return wheelhouse_service.restore(str(client_id), str(page_id))


@router.delete("/clients/{client_id}/wheelhouse/pages/{page_id}/permanent")
async def purge_page(
    client_id: UUID, page_id: UUID, auth: dict = Depends(require_auth),
) -> dict:
    """Permanently delete a soft-deleted draft."""
    wheelhouse_service.get_enabled_client(str(client_id))
    wheelhouse_service.purge(str(client_id), str(page_id))
    return {"ok": True}
