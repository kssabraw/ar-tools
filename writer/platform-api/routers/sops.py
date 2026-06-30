"""SOP / playbook store router.

Two layers:
  - agency-wide SOPs  → /sops                     (client_id IS NULL)
  - per-client SOPs   → /clients/{id}/sops        (scoped to one client)

Content arrives as parsed plain text — pasted directly, or extracted from an
uploaded document via /files/upload (field='sop') before the create call.
Service-role only; the frontend reads/writes through these routes.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from middleware.auth import require_admin, require_auth
from models.sops import Sop, SopCreateRequest, SopUpdateRequest
from services import sop_store

router = APIRouter(tags=["sops"])
logger = logging.getLogger(__name__)


# --- agency-wide ----------------------------------------------------------------
@router.get("/sops", response_model=list[Sop])
async def list_agency_sops(auth: dict = Depends(require_auth)) -> list[Sop]:
    """The agency-wide playbook (applies to every client)."""
    return [Sop(**r) for r in sop_store.list_sops(None)]


@router.post("/sops", response_model=Sop, status_code=201)
async def create_agency_sop(body: SopCreateRequest, auth: dict = Depends(require_admin)) -> Sop:
    row = sop_store.create_sop(
        client_id=None, title=body.title, content=body.content,
        category=body.category, source=body.source,
    )
    return Sop(**row)


# --- per-client -----------------------------------------------------------------
@router.get("/clients/{client_id}/sops", response_model=list[Sop])
async def list_client_sops(
    client_id: UUID, include_agency: bool = True, auth: dict = Depends(require_auth),
) -> list[Sop]:
    """A client's own SOPs, plus (by default) the agency-wide playbook so the UI can
    show the full set that will ground this client's Action Plan."""
    return [Sop(**r) for r in sop_store.list_sops(str(client_id), include_agency=include_agency)]


@router.post("/clients/{client_id}/sops", response_model=Sop, status_code=201)
async def create_client_sop(
    client_id: UUID, body: SopCreateRequest, auth: dict = Depends(require_admin),
) -> Sop:
    row = sop_store.create_sop(
        client_id=str(client_id), title=body.title, content=body.content,
        category=body.category, source=body.source,
    )
    return Sop(**row)


# --- shared update / delete (by id) ---------------------------------------------
@router.patch("/sops/{sop_id}", response_model=Sop)
async def update_sop(sop_id: UUID, body: SopUpdateRequest, auth: dict = Depends(require_admin)) -> Sop:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="no_fields")
    return Sop(**sop_store.update_sop(str(sop_id), updates))


@router.delete("/sops/{sop_id}", status_code=204, response_class=Response)
async def delete_sop(sop_id: UUID, auth: dict = Depends(require_admin)) -> Response:
    sop_store.delete_sop(str(sop_id))
    return Response(status_code=204)
