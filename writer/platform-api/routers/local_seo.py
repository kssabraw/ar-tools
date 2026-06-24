"""Local SEO module (#2) router.

platform-api owns auth + persistence and proxies analysis/generation/scoring
to the private nlp service. Every route is auth-gated; the nlp service is only
reachable server-side.

The long-running actions (generate / reoptimize / score / analyze / related /
social / find-page) are returned as heartbeat SSE streams via `sse_response`
so a multi-minute operation can't be killed by a load-balancer idle timeout.
The client reads the stream and resolves on the final done / error event.
GET / DELETE routes are instant and stay plain JSON.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from middleware.auth import require_auth
from models.local_seo import (
    LocalSeoAnalyzeRequest,
    LocalSeoFindPageRequest,
    LocalSeoGenerateRequest,
    LocalSeoPageDetail,
    LocalSeoPageListItem,
    LocalSeoRankabilityRequest,
    LocalSeoRankabilityResponse,
    LocalSeoRelatedPagesRequest,
    LocalSeoReoptimizeRequest,
    LocalSeoReoptimizeUrlRequest,
    LocalSeoScoreRequest,
    LocalSeoSiloPlanJob,
    LocalSeoSiloPlanRequest,
    LocalSeoSiloPlanResult,
    LocalSeoSocialPostsRequest,
    LocationSuggestion,
    PageTemplateDefaultRequest,
)
from services import local_seo_service, local_seo_silo
from sse import sse_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local_seo"])


@router.post("/clients/{client_id}/local-seo/generate")
async def generate_local_seo_page(
    client_id: UUID,
    body: LocalSeoGenerateRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    async def _run() -> dict:
        page = await local_seo_service.generate_page(
            client_id=str(client_id),
            keyword=body.keyword,
            location=body.location,
            location_code=body.location_code,
            user_id=auth["user_id"],
            force_refresh=body.force_refresh,
            page_template_url=body.page_template_url,
        )
        return LocalSeoPageDetail(**page).model_dump(mode="json")

    return sse_response(_run())


@router.put("/clients/{client_id}/local-seo/page-template-default")
async def set_local_seo_page_template_default(
    client_id: UUID,
    body: PageTemplateDefaultRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Save (or clear) the client's default page-template URL (Phase 3)."""
    return local_seo_service.set_page_template_default(str(client_id), body.page_template_url)


@router.post("/clients/{client_id}/local-seo/analyze")
async def analyze_local_seo(
    client_id: UUID,
    body: LocalSeoAnalyzeRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    return sse_response(local_seo_service.analyze(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        force_refresh=body.force_refresh,
    ))


@router.post("/clients/{client_id}/local-seo/find-page")
async def find_local_seo_page(
    client_id: UUID,
    body: LocalSeoFindPageRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    return sse_response(local_seo_service.find_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
    ))


@router.post("/clients/{client_id}/local-seo/score")
async def score_local_seo_page(
    client_id: UUID,
    body: LocalSeoScoreRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    return sse_response(local_seo_service.score_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        page_url=body.page_url,
        page_content=body.page_content,
        serp_analysis=body.serp_analysis,
        user_id=auth["user_id"],
        force_refresh=body.force_refresh,
    ))


@router.post("/clients/{client_id}/local-seo/related-pages")
async def related_local_seo_pages(
    client_id: UUID,
    body: LocalSeoRelatedPagesRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    return sse_response(local_seo_service.related_pages(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
    ))


@router.post("/clients/{client_id}/local-seo/silo-plan", response_model=LocalSeoSiloPlanJob)
async def start_local_seo_silo_plan(
    client_id: UUID,
    body: LocalSeoSiloPlanRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoSiloPlanJob:
    """Enqueue a Fanout-powered silo plan (runs minutes; poll for the result)."""
    job_id = await local_seo_silo.start_silo_plan(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        user_id=auth["user_id"],
    )
    return LocalSeoSiloPlanJob(job_id=job_id, status="pending")


@router.get(
    "/clients/{client_id}/local-seo/silo-plan/{job_id}",
    response_model=LocalSeoSiloPlanResult,
)
async def get_local_seo_silo_plan(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> LocalSeoSiloPlanResult:
    """Poll a silo-plan job; returns its status and (when complete) page targets."""
    return LocalSeoSiloPlanResult(**local_seo_silo.get_silo_plan(str(job_id), str(client_id)))


@router.post("/clients/{client_id}/local-seo/reoptimize")
async def reoptimize_local_seo_page(
    client_id: UUID,
    body: LocalSeoReoptimizeRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    async def _run() -> dict:
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
        return LocalSeoPageDetail(**page).model_dump(mode="json")

    return sse_response(_run())


@router.post("/clients/{client_id}/local-seo/reoptimize-url")
async def reoptimize_local_seo_url(
    client_id: UUID,
    body: LocalSeoReoptimizeUrlRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    """Score a live page by URL and reoptimize it only if it falls below the
    threshold (strong pages are skipped with a note). Backs the Reoptimization
    tab's single + bulk URL flows. SSE because score + rewrite can take minutes.

    Returns a `{status: 'reoptimized' | 'skipped', ...}` payload rather than a
    bare page, so the caller can render skip notes alongside rewrites.
    """
    return sse_response(local_seo_service.reoptimize_url(
        client_id=str(client_id),
        page_url=body.page_url,
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        user_id=auth["user_id"],
        score_threshold=body.score_threshold,
        publish_to_doc=body.publish_to_doc,
    ))


@router.post("/clients/{client_id}/local-seo/social-posts")
async def social_posts_local_seo(
    client_id: UUID,
    body: LocalSeoSocialPostsRequest,
    auth: dict = Depends(require_auth),
) -> StreamingResponse:
    return sse_response(local_seo_service.social_posts(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        page_content=body.page_content,
        serp_analysis=body.serp_analysis,
    ))


@router.post("/clients/{client_id}/local-seo/rankability", response_model=LocalSeoRankabilityResponse)
async def check_local_seo_rankability(
    client_id: UUID,
    body: LocalSeoRankabilityRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoRankabilityResponse:
    """Map-pack rankability report — can this client rank in the Maps pack for
    this keyword? Single point-in-time, deterministic, non-streaming (no LLM)."""
    result = await local_seo_service.check_rankability(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        sab_city=body.sab_city,
        user_id=auth["user_id"],
    )
    return LocalSeoRankabilityResponse(**result)


@router.get("/clients/{client_id}/local-seo/locations", response_model=list[LocationSuggestion])
async def search_local_seo_locations(
    client_id: UUID,
    query: str = Query(..., min_length=2),
    country: str | None = Query(None, min_length=2, max_length=2),
    auth: dict = Depends(require_auth),
) -> list[LocationSuggestion]:
    """Area-field typeahead: DataForSEO location suggestions scoped to the
    client's country (overridable via `country`)."""
    rows = await local_seo_service.search_locations(str(client_id), query, country=country)
    return [LocationSuggestion(**row) for row in rows]


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


@router.post("/local-seo/pages/{page_id}/publish")
async def publish_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict:
    """Publish a saved page to a Google Doc in the client's Drive folder."""
    return await local_seo_service.publish_page(str(page_id), auth["user_id"])
