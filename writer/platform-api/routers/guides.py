"""In-app Guides portal router.

Reads are auth-gated (any signed-in user); writes are admin-gated. The DB table is
the source of truth (seeded with defaults at startup). The editor lists all guides
(incl. disabled) via ?include_disabled=true.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from middleware.auth import require_admin, require_auth
from models.guides import Guide, GuideCreateRequest, GuideUpdateRequest
from services import guide_store

router = APIRouter(tags=["guides"])
logger = logging.getLogger(__name__)


@router.get("/guides", response_model=list[Guide])
async def list_guides(include_disabled: bool = False, auth: dict = Depends(require_auth)) -> list[Guide]:
    """All guides for display (enabled-only by default). The editor passes
    include_disabled=true to also see disabled drafts."""
    return [Guide(**r) for r in guide_store.list_guides(include_disabled=include_disabled)]


@router.get("/guides/{slug}", response_model=Guide)
async def get_guide(slug: str, auth: dict = Depends(require_auth)) -> Guide:
    row = guide_store.get_guide(slug)
    if not row:
        raise HTTPException(status_code=404, detail="guide_not_found")
    return Guide(**row)


@router.post("/guides", response_model=Guide, status_code=201)
async def create_guide(body: GuideCreateRequest, auth: dict = Depends(require_admin)) -> Guide:
    row = guide_store.create_guide(
        slug=body.slug, title=body.title, body=body.body, summary=body.summary,
        category=body.category, icon=body.icon, sort_order=body.sort_order,
    )
    return Guide(**row)


@router.patch("/guides/{guide_id}", response_model=Guide)
async def update_guide(guide_id: UUID, body: GuideUpdateRequest, auth: dict = Depends(require_admin)) -> Guide:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="no_fields")
    return Guide(**guide_store.update_guide(str(guide_id), updates))


@router.delete("/guides/{guide_id}", status_code=204, response_class=Response)
async def delete_guide(guide_id: UUID, auth: dict = Depends(require_admin)) -> Response:
    guide_store.delete_guide(str(guide_id))
    return Response(status_code=204)
