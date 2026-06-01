"""Local SEO module (#2) router.

platform-api owns auth + persistence and proxies analysis/generation/scoring
to the private nlp service. Every route is auth-gated; the nlp service is only
reachable server-side.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.local_seo import (
    LocalSeoAnalyzeRequest,
    LocalSeoFindPageRequest,
    LocalSeoGenerateRequest,
    LocalSeoPageDetail,
    LocalSeoPageListItem,
    LocalSeoRelatedPagesRequest,
    LocalSeoReoptimizeRequest,
    LocalSeoScoreRequest,
    LocalSeoSocialPostsRequest,
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


@router.post("/clients/{client_id}/local-seo/analyze")
async def analyze_local_seo(
    client_id: UUID,
    body: LocalSeoAnalyzeRequest,
    auth: dict = Depends(require_auth),
) -> dict[str, Any]:
    return await local_seo_service.analyze(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
    )


@router.post("/clients/{client_id}/local-seo/find-page")
async def find_local_seo_page(
    client_id: UUID,
    body: LocalSeoFindPageRequest,
    auth: dict = Depends(require_auth),
) -> dict[str, Any]:
    return await local_seo_service.find_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
    )


@router.post("/clients/{client_id}/local-seo/score")
async def score_local_seo_page(
    client_id: UUID,
    body: LocalSeoScoreRequest,
    auth: dict = Depends(require_auth),
) -> dict[str, Any]:
    return await local_seo_service.score_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        page_url=body.page_url,
        page_content=body.page_content,
        serp_analysis=body.serp_analysis,
    )


@router.post("/clients/{client_id}/local-seo/related-pages")
async def related_local_seo_pages(
    client_id: UUID,
    body: LocalSeoRelatedPagesRequest,
    auth: dict = Depends(require_auth),
) -> dict[str, Any]:
    return await local_seo_service.related_pages(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
    )


@router.post("/clients/{client_id}/local-seo/reoptimize", response_model=LocalSeoPageDetail, status_code=201)
async def reoptimize_local_seo_page(
    client_id: UUID,
    body: LocalSeoReoptimizeRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoPageDetail:
    page = await local_seo_service.reoptimize_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        existing_page_html=body.existing_page_html,
        existing_page_url=body.existing_page_url,
        deficiencies=body.deficiencies,
        serp_analysis=body.serp_analysis,
        user_id=auth["user_id"],
    )
    return LocalSeoPageDetail(**page)


@router.post("/clients/{client_id}/local-seo/social-posts")
async def social_posts_local_seo(
    client_id: UUID,
    body: LocalSeoSocialPostsRequest,
    auth: dict = Depends(require_auth),
) -> dict[str, Any]:
    return await local_seo_service.social_posts(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        page_content=body.page_content,
        serp_analysis=body.serp_analysis,
    )


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


@router.delete("/local-seo/pages/{page_id}")
async def delete_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    local_seo_service.delete_page(str(page_id))
    return {"deleted": True}
