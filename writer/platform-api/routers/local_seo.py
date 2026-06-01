"""Local SEO module (#2) router."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.local_seo import (
    LocalSeoGenerateRequest,
    LocalSeoPageDetail,
    LocalSeoPageListItem,
)
from services import local_seo_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local_seo"])


@router.post("/clients/{client_id}/local-seo/generate", response_model=LocalSeoPageDetail, status_code=201)
async def generate_local_seo_page(
    client_id: UUID,
    body: LocalSeoGenerateRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoPageDetail:
    page = await local_seo_service.generate_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        run_analysis=body.run_analysis,
        user_id=auth["user_id"],
    )
    return LocalSeoPageDetail(**page)


@router.get("/clients/{client_id}/local-seo/pages", response_model=list[LocalSeoPageListItem])
async def list_local_seo_pages(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> list[LocalSeoPageListItem]:
    return [LocalSeoPageListItem(**row) for row in local_seo_service.list_pages(str(client_id))]


@router.get("/local-seo/pages/{page_id}", response_model=LocalSeoPageDetail)
async def get_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> LocalSeoPageDetail:
    return LocalSeoPageDetail(**local_seo_service.get_page(str(page_id)))
